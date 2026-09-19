# EduPath Domain Knowledge Pack

This directory is the **Phase 3** deliverable (design doc §11.5, §39.1): the
curated skill graph, resource catalog, misconception catalog, assessment item
bank, and demo dataset that later phases (Gap Engine, Planner, Assessor,
Reflection, Tutor) read from. It is intentionally **decoupled from
application code** at the source level — nothing under `backend/app/`
hand-edits or generates this JSON — but it is now the seed input to a real
ingestion pipeline: `backend/app/catalog/ingest.py` (run via
`backend/scripts/seed_catalog.py`) reads `data/dataset/*.json`, validates it
(`backend/app/graph/validation.py`), and loads it into Postgres, which
`backend/app/graph/loader.py` then loads into NetworkX at query time, per
`ARCHITECTURE_CONTRACTS.md` §5 ("Graph is curated offline, versioned, loaded
from Postgres into NetworkX at process startup"). No backend/frontend code
reads these JSON files directly outside that ingestion path.

## Layout

```
data/
  README.md                    - this file
  scripts/
    build_dataset.py           - canonical SOURCE of the curated content
    validate_dataset.py        - validates the generated JSON
  dataset/                     - generated output (do not hand-edit)
    meta.json                  - graph_version, generated_at, entity counts
    skills.json                - ~150-250 curated skills (design §11.2)
    roles.json                 - 3 target roles + required-skill weights
    skill_edges.json           - PREREQUISITE_OF / PART_OF / RELATED_TO edges
    resources.json             - curated learning-resource catalog
    misconceptions.json        - misconception catalog
    assessment_items.json      - validated initial item bank
    demo/
      demo_learner.json        - demo persona "Asha" (design §38.1)
      demo_resume.md           - demo resume text (matches design §38.1)
      demo_learner_state.json  - seeded skill states (design §13.4 worked example)
      demo_scenario.json       - seeded misconception/item-set/scripted-attempt config
```

## Regenerating

`data/dataset/*.json` is **generated**, not hand-authored. To change the
data, edit the Python literals in `data/scripts/build_dataset.py` (skills,
roles, edges, resources, misconceptions, items, demo dataset), then:

```bash
python data/scripts/build_dataset.py
python data/scripts/validate_dataset.py
```

`build_dataset.py` has no third-party dependencies (stdlib only: `json`,
`datetime`, `pathlib`) and works with any Python 3.9+.

## Validating

`validate_dataset.py` checks (see its module docstring for the full list):

1. Duplicate IDs across every entity collection.
2. Missing references (skill edges, role requirements, resource skill
   targets/prerequisites, misconception skill/root refs, assessment item
   skill/misconception refs, demo dataset refs).
3. The hard-`PREREQUISITE_OF` subgraph is a DAG (cycle check —
   `ARCHITECTURE_CONTRACTS.md` §5 build-time invariant).
4. Orphan skills (referenced by nothing — no edge, role, resource,
   misconception, or item).
5. Every role-required skill has ≥ 1 catalog resource (warning if not).
6. Every misconception's `root_prerequisite` is a hard-prerequisite ancestor
   of its `affected_skill` in the curated graph (warning if not — this is a
   curation-quality check, not a structural requirement).
7. Every assessment item has exactly one correct option and resolves its
   `skill_id`/`misconception_id` references.
8. Resource URLs are well-formed `https://` URLs; hosts not on the
   reviewed-domain allowlist are flagged for manual re-review (this script
   makes **no live network calls** — see "Link validation" below for how
   the URLs in this pack were actually checked).
9. Assessable-skill item-bank coverage report (informational — see "Known
   scope decisions" below).

Exit code 0 = no hard errors. As of the last regeneration in this repo, the
pack validates with **0 errors and 0 warnings**.

## Link validation

Design doc §15.2 requires a link-validation job and forbids inventing URLs.
For this pack:

- Every resource URL is a real page on a reputable official/educational
  domain (language/framework docs, Khan Academy, 3Blue1Brown, Kaggle Learn,
  Hugging Face, OWASP, PostgreSQL/SQLAlchemy docs, etc.) — no URL was
  fabricated.
- A sample of higher-risk URLs (deep links, less-common domains, one PDF)
  was live-checked during curation; two dead/redirected links found that way
  (`linuxjourney.com` → 301 to a different site; `mode.com/sql-tutorial/...`
  → 301 to `thoughtspot.com/sql-tutorial/...` after Mode Analytics' content
  moved) were fixed to their real current destination.
- The full 140-resource catalog has **not** been exhaustively live-checked
  link-by-link in this environment. Before a live demo or before wiring a
  real link-validation job (Phase 6, design §15.2), run a HEAD-request sweep
  over `resources.json`'s `url` field and update `link_status` accordingly.
  `validate_dataset.py` checks URL well-formedness and domain reputation
  only, not liveness.

## Known scope decisions (read before assuming full coverage)

- **Assessment item bank is partial by design.** Design §11.5 asks that
  *every assessable skill* eventually have ≥ 6 mixed-difficulty items; doing
  that for all ~150 assessable skills here (~900+ items) was out of scope
  for an initial pack. This pack seeds **95 items across 23 skills** to a
  validated standard — full 6-item coverage on the demo chain
  (`chain_rule`, `backpropagation`, `training_neural_networks`,
  `neural_network_fundamentals`) plus a representative spread of other core
  skills (SQL joins, hypothesis testing, recursion, REST API design, auth,
  Docker, etc.), each tied to a real catalogued misconception where
  applicable. `validate_dataset.py`'s coverage report (check #9 above) lists
  exactly which assessable skills still have 0 items — treat that as the
  backlog for Phase 7 (Assessor), not a bug in this pack.
- **Graph is scoped to 3 roles**, exactly as design §11.5 specifies: Machine
  Learning Engineer, Data Analyst, Backend Developer. 158 skills, 203
  skill-to-skill edges (prerequisite/part-of/related-to), 140 resources, 18
  misconceptions.
- **`link_status` is seeded as `"ok"`** for every resource (verification
  timestamp `last_verified_at: "2026-09-19"`) based on the spot-check above,
  not a full crawl — see "Link validation".
- **Every edge, resource, misconception and item in this pack is
  machine-authored against the design doc's rules, not team-reviewed by a
  human yet.** `reviewed_by` is set to `"edupath-phase3-curation"` as a
  placeholder for that review pass — design §11.5 calls for human review of
  every LLM/machine-drafted prerequisite edge before it's trusted in
  production gap analysis. Treat this pack as a strong first draft, not a
  final-reviewed graph.

## Consuming this data

**Implemented (Phase 3):** `data/dataset/*.json` is the seed data for
`backend/app/catalog/ingest.py`, which loads it into the Postgres tables
`Skill`, `SkillEdge`, `Role`, `RoleRequirement`, `Misconception`, `Resource`,
`ResourceSkill`, `PracticeItem`, `GraphMeta` (migration
`0002_skill_graph_catalog`). Run it with:

```bash
cd backend
alembic upgrade head
python scripts/seed_catalog.py
```

`backend/app/graph/loader.py` then builds a NetworkX graph from those
Postgres tables (not from this JSON directly) — `SkillGraphService`
(`backend/app/graph/queries.py`) is the read API later phases should use.
Do not read these JSON files directly from request-handling code; go through
that pipeline.

The `graph_version` in `meta.json` (currently `v0.1.0-domain-pack`) is copied
into `GraphMeta` on every ingestion run and should be referenced by every
`DecisionRecord` produced against this graph, per
`ARCHITECTURE_CONTRACTS.md` §14 (not yet applicable — `DecisionRecord`
doesn't exist until Phase 4, Gap Analysis).
