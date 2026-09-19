"""Graph invariants (design §11.5 step 4; ARCHITECTURE_CONTRACTS.md §5's
build-time DAG invariant).

Operates on plain collections shaped exactly like `data/dataset/*.json`
(dicts with the domain-pack's field names — `affected_skill`,
`root_prerequisite`, etc.) so it can run both offline against the curated
JSON (parity with `data/scripts/validate_dataset.py`, which this module's
checks are a direct, DB-independent port of) and inline during catalog
ingestion (`app/catalog/ingest.py`), before anything is written to Postgres —
"validate, then commit," matching the LLMGateway's schema-validate-then-act
pattern (ARCHITECTURE_CONTRACTS.md §6).

A hard error means the graph must not be trusted/loaded (§11.5's build-time
invariants: cycles, missing references, duplicate IDs, malformed items). A
warning is a curation-quality flag that does not block a build (missing
resource coverage, an under-verified misconception root, an unreviewed
resource domain).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # Informational: assessable skills with >=6 / 1-5 / 0 items (design §11.5
    # step 4's "every assessable skill has >= 6 items" target — not a hard
    # gate this phase, see data/README.md "Known scope decisions").
    item_coverage: dict[str, list] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


class GraphValidationError(Exception):
    def __init__(self, report: ValidationReport) -> None:
        self.report = report
        super().__init__(f"{len(report.errors)} graph invariant violation(s): {'; '.join(report.errors)}")


# Domains spot-checked during curation (data/README.md "Link validation").
# A resource whose host is not here is not an error -- just flagged for
# manual re-review, exactly as data/scripts/validate_dataset.py does.
REVIEWED_DOMAIN_ALLOWLIST: frozenset[str] = frozenset(
    {
        "khanacademy.org", "3blue1brown.com", "developers.google.com", "docs.python.org",
        "realpython.com", "docs.pytest.org", "numpy.org", "pandas.pydata.org", "matplotlib.org",
        "seaborn.pydata.org", "kaggle.com", "scikit-learn.org", "pytorch.org", "d2l.ai",
        "cs231n.github.io", "cs231n.stanford.edu", "colah.github.io", "jalammar.github.io",
        "huggingface.co", "platform.openai.com", "mlflow.org", "docs.wandb.ai", "fastapi.tiangolo.com",
        "docs.evidentlyai.com", "developer.mozilla.org", "restfulapi.net", "expressjs.com", "jwt.io",
        "owasp.org", "redis.io", "rabbitmq.com", "martinfowler.com", "github.com", "docs.nginx.com",
        "learning.postman.com", "swagger.io", "graphql.org", "grpc.io", "stripe.com",
        "cloudflare.com", "12factor.net", "docs.docker.com", "kubernetes.io", "docs.github.com",
        "aws.amazon.com", "calculator.aws", "developer.hashicorp.com", "grafana.com", "git-scm.com",
        "google.github.io", "atlassian.com", "writethedocs.org", "thoughtspot.com",
        "klipfolio.com", "dataversity.net", "ftc.gov", "stitchdata.com",
        "cheatsheetseries.owasp.org", "support.microsoft.com", "exceljet.net", "help.tableau.com",
        "learn.microsoft.com", "hbr.org", "sqlbolt.com", "postgresql.org", "mongodb.com",
        "docs.sqlalchemy.org", "alembic.sqlalchemy.org", "databasestar.com",
        "docs.ultralytics.com", "freecodecamp.org", "bigocheatsheet.com",
        "geeksforgeeks.org", "refactoring.guru", "optimizely.com", "tensorflow.org",
        "shap.readthedocs.io", "docs.opencv.org", "ubuntu.com",
    }
)


class GraphValidator:
    """Stateless — one call to `validate()` per catalog snapshot."""

    def validate(
        self,
        *,
        skills: list[dict],
        roles: list[dict],
        edges: list[dict],
        resources: list[dict],
        misconceptions: list[dict],
        items: list[dict],
    ) -> ValidationReport:
        report = ValidationReport()

        skill_ids = self._check_duplicates(skills, "skill_id", "skill", report)
        role_ids = self._check_duplicates(roles, "role_id", "role", report)
        resource_ids = self._check_duplicates(resources, "resource_id", "resource", report)
        misconception_ids = self._check_duplicates(misconceptions, "misconception_id", "misconception", report)
        self._check_duplicates(items, "item_id", "assessment item", report)
        self._check_duplicate_edges(edges, report)

        self._check_edge_refs(edges, skill_ids, report)
        self._check_role_refs(roles, skill_ids, report)
        self._check_resource_refs(resources, skill_ids, report)
        self._check_misconception_refs(misconceptions, skill_ids, resource_ids, report)
        self._check_item_refs(items, skill_ids, misconception_ids, report)

        self._check_dag(skill_ids, edges, report)
        self._check_orphans(skill_ids, roles, edges, resources, misconceptions, items, report)
        self._check_role_resource_coverage(roles, resources, report)
        self._check_misconception_ancestry(misconceptions, edges, skill_ids, report)
        self._check_resource_urls(resources, report)
        report.item_coverage = self._item_coverage(skills, items)

        return report

    # -- structural -----------------------------------------------------

    @staticmethod
    def _check_duplicates(items: list[dict], key: str, label: str, report: ValidationReport) -> set[str]:
        seen: set[str] = set()
        for it in items:
            k = it[key]
            if k in seen:
                report.errors.append(f"Duplicate {label} id: {k!r}")
            seen.add(k)
        return seen

    @staticmethod
    def _check_duplicate_edges(edges: list[dict], report: ValidationReport) -> None:
        seen: set[tuple] = set()
        for e in edges:
            key = (e["from_skill"], e["to_skill"], e["type"])
            if key in seen:
                report.errors.append(f"Duplicate skill edge: {key}")
            seen.add(key)

    @staticmethod
    def _check_edge_refs(edges: list[dict], skill_ids: set[str], report: ValidationReport) -> None:
        for e in edges:
            if e["from_skill"] not in skill_ids:
                report.errors.append(f"Edge references unknown from_skill: {e['from_skill']!r} ({e['type']})")
            if e["to_skill"] not in skill_ids:
                report.errors.append(f"Edge references unknown to_skill: {e['to_skill']!r} ({e['type']})")

    @staticmethod
    def _check_role_refs(roles: list[dict], skill_ids: set[str], report: ValidationReport) -> None:
        for r in roles:
            for rs in r["required_skills"]:
                if rs["skill_id"] not in skill_ids:
                    report.errors.append(f"Role {r['role_id']!r} requires unknown skill: {rs['skill_id']!r}")

    @staticmethod
    def _check_resource_refs(resources: list[dict], skill_ids: set[str], report: ValidationReport) -> None:
        for res in resources:
            for st in res["skill_targets"]:
                if st["skill_id"] not in skill_ids:
                    report.errors.append(f"Resource {res['resource_id']!r} targets unknown skill: {st['skill_id']!r}")
            for p in res["prerequisite_skill_ids"]:
                if p not in skill_ids:
                    report.errors.append(f"Resource {res['resource_id']!r} has unknown prerequisite skill: {p!r}")
            if not res["skill_targets"]:
                report.errors.append(f"Resource {res['resource_id']!r} has no skill_targets")

    @staticmethod
    def _check_misconception_refs(
        misconceptions: list[dict], skill_ids: set[str], resource_ids: set[str], report: ValidationReport
    ) -> None:
        for m in misconceptions:
            if m["affected_skill"] not in skill_ids:
                report.errors.append(
                    f"Misconception {m['misconception_id']!r} has unknown affected_skill: {m['affected_skill']!r}"
                )
            if m["root_prerequisite"] not in skill_ids:
                report.errors.append(
                    f"Misconception {m['misconception_id']!r} has unknown root_prerequisite: "
                    f"{m['root_prerequisite']!r}"
                )
            for rid in m["remediation_candidates"]:
                if rid not in resource_ids:
                    report.errors.append(
                        f"Misconception {m['misconception_id']!r} has unknown remediation resource: {rid!r}"
                    )

    @staticmethod
    def _check_item_refs(
        items: list[dict], skill_ids: set[str], misconception_ids: set[str], report: ValidationReport
    ) -> None:
        for it in items:
            if it["skill_id"] not in skill_ids:
                report.errors.append(f"Item {it['item_id']!r} references unknown skill: {it['skill_id']!r}")
            key_count = sum(1 for o in it["options"] if o["is_key"])
            if key_count != 1:
                report.errors.append(
                    f"Item {it['item_id']!r} must have exactly one correct option, found {key_count}"
                )
            for o in it["options"]:
                if o.get("misconception_id") is not None and o["misconception_id"] not in misconception_ids:
                    report.errors.append(f"Item {it['item_id']!r} option tags unknown misconception: {o['misconception_id']!r}")

    # -- graph invariants -------------------------------------------------

    @staticmethod
    def _check_dag(skill_ids: set[str], edges: list[dict], report: ValidationReport) -> None:
        """ARCHITECTURE_CONTRACTS.md §5: the hard-prerequisite subgraph must
        be a DAG. Iterative DFS with an explicit stack (no recursion limit
        concerns at ~200 nodes, but keeps the same shape as the offline
        validator's proven implementation)."""
        adj: dict[str, list[str]] = defaultdict(list)
        for e in edges:
            if e["type"] == "PREREQUISITE_OF" and e.get("strength") == "hard":
                adj[e["from_skill"]].append(e["to_skill"])

        WHITE, GRAY, BLACK = 0, 1, 2
        color = {s: WHITE for s in skill_ids}

        for start in skill_ids:
            if color[start] != WHITE:
                continue
            stack = [(start, iter(adj.get(start, [])))]
            color[start] = GRAY
            path = [start]
            while stack:
                node, it = stack[-1]
                advanced = False
                for nxt in it:
                    if color.get(nxt, WHITE) == GRAY:
                        cycle = path[path.index(nxt):] + [nxt]
                        report.errors.append(f"Hard-prerequisite graph has a cycle: {' -> '.join(cycle)}")
                        return
                    if color.get(nxt, WHITE) == WHITE:
                        color[nxt] = GRAY
                        stack.append((nxt, iter(adj.get(nxt, []))))
                        path.append(nxt)
                        advanced = True
                        break
                if not advanced:
                    color[node] = BLACK
                    stack.pop()
                    path.pop()

    @staticmethod
    def _check_orphans(
        skill_ids: set[str],
        roles: list[dict],
        edges: list[dict],
        resources: list[dict],
        misconceptions: list[dict],
        items: list[dict],
        report: ValidationReport,
    ) -> None:
        referenced: set[str] = set()
        for e in edges:
            referenced.add(e["from_skill"])
            referenced.add(e["to_skill"])
        for r in roles:
            for rs in r["required_skills"]:
                referenced.add(rs["skill_id"])
        for res in resources:
            for st in res["skill_targets"]:
                referenced.add(st["skill_id"])
        for m in misconceptions:
            referenced.add(m["affected_skill"])
            referenced.add(m["root_prerequisite"])
        for it in items:
            referenced.add(it["skill_id"])

        for orphan in sorted(skill_ids - referenced):
            report.errors.append(
                f"Orphan skill (no edge, role requirement, resource, misconception or item references it): "
                f"{orphan!r}"
            )

    @staticmethod
    def _check_role_resource_coverage(roles: list[dict], resources: list[dict], report: ValidationReport) -> None:
        skill_to_resources: dict[str, list[str]] = defaultdict(list)
        for res in resources:
            for st in res["skill_targets"]:
                skill_to_resources[st["skill_id"]].append(res["resource_id"])

        for r in roles:
            for rs in r["required_skills"]:
                if not skill_to_resources.get(rs["skill_id"]):
                    report.warnings.append(
                        f"Role {r['role_id']!r} requires skill {rs['skill_id']!r} with 0 catalog resources"
                    )

    @staticmethod
    def _check_misconception_ancestry(
        misconceptions: list[dict], edges: list[dict], skill_ids: set[str], report: ValidationReport
    ) -> None:
        rev: dict[str, list[str]] = defaultdict(list)
        for e in edges:
            if e["type"] == "PREREQUISITE_OF" and e.get("strength") == "hard":
                rev[e["to_skill"]].append(e["from_skill"])

        def hard_ancestors(skill_id: str) -> set[str]:
            seen: set[str] = set()
            stack = [skill_id]
            while stack:
                cur = stack.pop()
                for p in rev.get(cur, []):
                    if p not in seen:
                        seen.add(p)
                        stack.append(p)
            return seen

        for m in misconceptions:
            if m["affected_skill"] not in skill_ids or m["root_prerequisite"] not in skill_ids:
                continue
            if m["root_prerequisite"] == m["affected_skill"]:
                continue
            if m["root_prerequisite"] not in hard_ancestors(m["affected_skill"]):
                report.warnings.append(
                    f"Misconception {m['misconception_id']!r}: root_prerequisite "
                    f"{m['root_prerequisite']!r} is not a hard-prerequisite ancestor of "
                    f"affected_skill {m['affected_skill']!r} (check the edge is curated correctly)"
                )

    @staticmethod
    def _check_resource_urls(resources: list[dict], report: ValidationReport) -> None:
        for res in resources:
            url = res["url"]
            parsed = urlparse(url)
            if parsed.scheme != "https" or not parsed.netloc:
                report.errors.append(f"Resource {res['resource_id']!r} has a malformed/non-https URL: {url!r}")
                continue
            host = parsed.netloc.lower()
            bare_host = host[4:] if host.startswith("www.") else host
            if host not in REVIEWED_DOMAIN_ALLOWLIST and bare_host not in REVIEWED_DOMAIN_ALLOWLIST:
                report.warnings.append(
                    f"Resource {res['resource_id']!r} URL host {host!r} not in the reviewed allowlist — "
                    f"re-verify manually: {url}"
                )
            if res["link_status"] not in ("ok", "redirected", "broken"):
                report.errors.append(f"Resource {res['resource_id']!r} has invalid link_status: {res['link_status']!r}")

    @staticmethod
    def _item_coverage(skills: list[dict], items: list[dict]) -> dict[str, list]:
        items_by_skill: dict[str, list] = defaultdict(list)
        for it in items:
            items_by_skill[it["skill_id"]].append(it["item_id"])

        zero, under_six, full = [], [], []
        for s in skills:
            if not s["assessable"]:
                continue
            n = len(items_by_skill.get(s["skill_id"], []))
            if n == 0:
                zero.append(s["skill_id"])
            elif n < 6:
                under_six.append(s["skill_id"])
            else:
                full.append(s["skill_id"])
        return {"full_coverage": full, "under_six": under_six, "zero": zero}
