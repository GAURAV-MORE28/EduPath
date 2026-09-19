"""Skill-Gap Engine (design §13; ARCHITECTURE_CONTRACTS.md §4).

`analyze_gaps` is a pure function over already-loaded data: a `SkillGraphService`
(Phase 3) and two small, framework-independent record lists describing a
learner's current skill state and evidence. It never touches the database or
an LLM gateway itself — the API layer (`app/api/v1/gap.py`) is responsible for
reading `LearnerSkillState`/`Evidence` rows and converting them into
`LearnerSkillRecord`/`EvidenceRecord` before calling in. This mirrors
`app/graph/queries.py`'s shape (a deterministic service over an in-memory
graph) and is what makes the algorithm itself unit-testable with hand-built
fixtures, no DB required (design's effort table: "Gap Engine | Easy-Moderate |
Real | Pure functions; unit-testable").

**Deterministic only** (ARCHITECTURE_CONTRACTS.md §4): no gateway/agent
imports anywhere in this module. An LLM may narrate this module's output
afterward; it never participates in computing it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.core.thresholds import LEVEL_MASTERY_THRESHOLD, LEVEL_MIN_N_OBS, LEVEL_TIER_REQUIRED, tier_at_least
from app.graph.queries import SkillGraphService, UnknownSkillError

MET = "MET"
WEAK = "WEAK"
UNVERIFIED = "UNVERIFIED"
MISSING = "MISSING"
BLOCKED = "BLOCKED"

# The two statuses that count as a "blocking" prerequisite state (design §13.2:
# "BLOCKED: a hard prerequisite is WEAK or MISSING (an UNVERIFIED prerequisite
# does not block; it gets a probe first)").
_BLOCKING_STATUSES = (WEAK, MISSING)


# ---------------------------------------------------------------------------
# Inputs (framework-independent — no ORM/session dependency; see module docstring)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LearnerSkillRecord:
    """The subset of `LearnerSkillState` (app/db/models.py) the Gap Engine
    needs. `alpha`/`beta` give the Beta-count mastery estimate (design
    §10.4); `tier_max` is the strongest evidence tier on file for this skill;
    `n_obs` is the assessed-item count (only relevant to the L3 tier gate)."""

    skill_id: str
    alpha: float
    beta: float
    tier_max: str  # E0-E3
    n_obs: int = 0


@dataclass(frozen=True)
class EvidenceRecord:
    """The subset of `Evidence` the Gap Engine needs — just enough to
    attribute `evidence_ids[]` on each `SkillGapEntry`/`Strength` for
    provenance (design §12.5's "what evidence says I know X" queries)."""

    evidence_id: str
    skill_id: str
    tier: str


# ---------------------------------------------------------------------------
# Outputs (design §25.2 `SkillGap` / `LearningObjective`, §13.5)
# ---------------------------------------------------------------------------


@dataclass
class SkillGapEntry:
    skill_id: str
    label: str
    status: str  # MET | WEAK | UNVERIFIED | MISSING | BLOCKED -- user-facing (BLOCKED overlays the rest)
    gap_type: str  # the underlying diagnosis before the BLOCKED overlay: met | weak | unverified | missing
    required_level: int
    current_level: int  # highest level (0-3) the tier gate actually confirms; 0 = none confirmed
    blocked_by: list[str] = field(default_factory=list)  # direct hard prerequisites causing BLOCKED
    root_of: list[str] = field(default_factory=list)  # in-scope BLOCKED descendants this gap is gating
    priority: float = 0.0
    ordering_layer: int = 0
    evidence_ids: list[str] = field(default_factory=list)
    audit_flags: list[str] = field(default_factory=list)  # flag_types from `audit_flags` that name this skill


@dataclass
class Strength:
    """An evidence-backed `MET` skill (design §13.1's `strengths[]`)."""

    skill_id: str
    label: str
    required_level: int
    current_level: int
    tier_max: str
    mastery: float
    evidence_ids: list[str] = field(default_factory=list)


@dataclass
class AuditFlag:
    """design §12.4. `flag_type` is one of `claimed_without_evidence`,
    `claim_evidence_mismatch`, `stale_or_weak_evidence`."""

    flag_type: str
    skill_id: str
    message: str
    related_skill_ids: list[str] = field(default_factory=list)


@dataclass
class LearningObjective:
    """design §13.5. `objective_type="probe"` implements **verify-before-teach**
    (the Phase 5 brief's explicit requirement): an `UNVERIFIED` gap gets a
    probe objective, never a beginner-lesson objective, until real evidence
    resolves it one way or the other.

    `est_minutes_low`/`est_minutes_high` are deliberately left `None` here —
    design §13.5 sources them "from candidate resources at this level band",
    which is the Resource Retriever/Ranker's job (Phase 6, design §14.3/§15),
    not the Gap Engine's. Wire them once that service exists rather than
    duplicating resource-eligibility logic here (design §14.1: "Mixing these
    [retrieval] planes... is explicitly avoided").
    """

    objective_id: str
    skill_id: str
    from_status: str  # WEAK | UNVERIFIED | MISSING (never MET or BLOCKED -- see analyze_gaps)
    objective_type: str  # "probe" | "lesson"
    target_level: int
    priority: float
    prerequisite_objective_ids: list[str] = field(default_factory=list)
    acceptance_criteria: dict = field(default_factory=dict)
    est_minutes_low: int | None = None
    est_minutes_high: int | None = None
    reason_ref: str = ""


@dataclass
class GapAnalysisResult:
    role_id: str
    graph_version: str
    scope_skill_ids: set[str]
    gaps: list[SkillGapEntry] = field(default_factory=list)
    strengths: list[Strength] = field(default_factory=list)
    audit_flags: list[AuditFlag] = field(default_factory=list)
    objectives: list[LearningObjective] = field(default_factory=list)
    layers: list[list[str]] = field(default_factory=list)  # topological ordering layers over non-MET scope skills
    # Hard PREREQUISITE_OF edges with both endpoints in scope -- enough for the
    # frontend to draw the gap graph without re-deriving it from raw skill_edges.
    prerequisite_edges: list[tuple[str, str]] = field(default_factory=list)


def objective_id_for(role_id: str, skill_id: str) -> str:
    """Deterministic, reproducible objective IDs (no uuid4) -- the Gap Engine
    recomputes on demand (like `role_subgraph`, design §12.1), so the same
    (role, skill) pair must always yield the same ID across runs for the
    Planner (Phase 5) to reference stably before any persistence exists."""
    return f"obj.{role_id}.{skill_id}"


# ---------------------------------------------------------------------------
# Tier-gate classification (design §12.3 / §13.3)
# ---------------------------------------------------------------------------


def _mastery_estimate(state: LearnerSkillRecord | None) -> float:
    if state is None:
        return 0.0
    total = state.alpha + state.beta
    return state.alpha / total if total > 0 else 0.0


def _level_met(state: LearnerSkillRecord | None, level: int) -> bool:
    """The tier gate for `MET` at required level *L* (ARCHITECTURE_CONTRACTS.md
    §3): mastery >= threshold(L) AND tier_max >= tier_required(L), plus L3's
    extra `n_obs >= 3`. A self-report or inference alone (tier_max == E0)
    can never satisfy this for any level, by construction."""
    if state is None:
        return False
    if _mastery_estimate(state) < LEVEL_MASTERY_THRESHOLD[level]:
        return False
    if not tier_at_least(state.tier_max, LEVEL_TIER_REQUIRED[level]):
        return False
    if state.n_obs < LEVEL_MIN_N_OBS.get(level, 0):
        return False
    return True


def _current_level(state: LearnerSkillRecord | None) -> int:
    """Highest level (3, 2, 1) whose tier gate `state` actually clears; 0 if
    none. Used only for display (`SkillGapEntry.current_level`), never to
    decide status -- that is always relative to the skill's *required*
    level, computed separately."""
    for level in (3, 2, 1):
        if _level_met(state, level):
            return level
    return 0


def _classify(state: LearnerSkillRecord | None, required_level: int) -> str:
    """design §13.3's per-skill branch, before the BLOCKED overlay."""
    if state is None:
        return MISSING
    if _level_met(state, required_level):
        return MET
    if tier_at_least(state.tier_max, "E1"):
        # Some assessed/artifact/documented evidence exists, just not enough
        # for the required level yet.
        return WEAK
    # tier_max == "E0": self-reported / listed only -- a claim, not evidence.
    return UNVERIFIED


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def analyze_gaps(
    role_id: str,
    skill_records: list[LearnerSkillRecord],
    evidence_records: list[EvidenceRecord],
    graph: SkillGraphService,
) -> GapAnalysisResult:
    """design §13.3's `analyze_gaps(role, learner, graph)`, implemented
    against this project's actual data shapes. Raises `UnknownRoleError`
    (propagated from `graph.role_subgraph`) if `role_id` isn't curated --
    ARCHITECTURE_CONTRACTS.md §5: "role not supported", never invent one.
    """
    role = graph.role_subgraph(role_id)  # required skills + hard-prerequisite closure
    scope = role.skill_ids

    state_by_skill = {r.skill_id: r for r in skill_records if r.skill_id in scope}
    evidence_by_skill: dict[str, list[EvidenceRecord]] = {}
    for e in evidence_records:
        if e.skill_id in scope:
            evidence_by_skill.setdefault(e.skill_id, []).append(e)

    # -- required level per scope skill (design §13.3) ----------------------
    req_level: dict[str, int] = {}
    for s in scope:
        base = role.required_levels.get(s, 0)
        dependent_min = max(
            (min_level for to, min_level in graph.hard_prerequisite_out_edges(s) if to in scope),
            default=1,
        )
        req_level[s] = min(max(base, dependent_min), 3)  # clamp: only L1-L3 are defined (design §10.4)

    # -- raw per-skill status (before the BLOCKED overlay) -------------------
    raw_status = {s: _classify(state_by_skill.get(s), req_level[s]) for s in scope}

    # -- BLOCKED overlay: hard prerequisite is WEAK or MISSING ---------------
    hard_parents = {s: [p for p in graph.direct_prerequisites(s, include_soft=False) if p in scope] for s in scope}
    blocked = {
        s
        for s in scope
        if raw_status[s] != MET and any(raw_status[p] in _BLOCKING_STATUSES for p in hard_parents[s])
    }
    root_gaps = {s for s in scope if raw_status[s] != MET and s not in blocked}

    final_status = {s: (BLOCKED if s in blocked else raw_status[s]) for s in scope}

    # -- priority (design §13.3) --------------------------------------------
    hard_descendants_in_scope = {s: graph.hard_descendants(s) & scope for s in scope}
    unmet_dependents = {s: sum(1 for d in hard_descendants_in_scope[s] if raw_status[d] != MET) for s in scope}

    def _weight_reaching(skill_id: str) -> int:
        candidates = [role.weights[skill_id]] if skill_id in role.weights else []
        candidates += [role.weights[d] for d in hard_descendants_in_scope[skill_id] if d in role.weights]
        return max(candidates) if candidates else 1

    priority = {
        s: (_weight_reaching(s) * (1 + math.log(1 + unmet_dependents[s])) if s in root_gaps | blocked else 0.0)
        for s in scope
    }

    # -- ordering layers over the unmet subgraph ------------------------------
    unmet_nodes = {s for s in scope if raw_status[s] != MET}
    layers = graph.topological_layers(unmet_nodes) if unmet_nodes else []
    layer_of = {s: i for i, layer in enumerate(layers) for s in layer}

    # -- audit flags (design §12.4) ------------------------------------------
    # `claim_evidence_mismatch` scans claimed skills graph-wide (a PART_OF
    # parent like "Full Stack" is usually an umbrella node with no
    # PREREQUISITE_OF edges of its own, so it is typically *not* itself a
    # hard-ancestor of any role-required skill and therefore never appears
    # in `scope` -- restricting the parent search to `scope` would silently
    # never fire this rule). `claimed_without_evidence`/`stale_or_weak_evidence`
    # stay role-scoped, since both depend on role-relative weight/required
    # level. See `_compute_audit_flags`.
    all_state_by_skill = {r.skill_id: r for r in skill_records}
    audit_flags = _compute_audit_flags(scope, state_by_skill, all_state_by_skill, req_level, role.weights, graph)
    flags_by_skill: dict[str, list[str]] = {}
    for flag in audit_flags:
        flags_by_skill.setdefault(flag.skill_id, []).append(flag.flag_type)

    # -- assemble SkillGapEntry per scope skill -------------------------------
    gaps: list[SkillGapEntry] = []
    strengths: list[Strength] = []
    for s in scope:
        state = state_by_skill.get(s)
        skill = graph.get_skill(s)
        evidence_ids = [e.evidence_id for e in evidence_by_skill.get(s, [])]
        blocked_by = [p for p in hard_parents[s] if raw_status[p] in _BLOCKING_STATUSES] if s in blocked else []
        root_of = [d for d in hard_descendants_in_scope[s] if final_status[d] == BLOCKED]

        gaps.append(
            SkillGapEntry(
                skill_id=s,
                label=skill.label,
                status=final_status[s],
                gap_type=raw_status[s].lower(),
                required_level=req_level[s],
                current_level=_current_level(state),
                blocked_by=blocked_by,
                root_of=root_of,
                priority=priority[s],
                ordering_layer=layer_of.get(s, -1),
                evidence_ids=evidence_ids,
                audit_flags=flags_by_skill.get(s, []),
            )
        )
        if final_status[s] == MET:
            strengths.append(
                Strength(
                    skill_id=s,
                    label=skill.label,
                    required_level=req_level[s],
                    current_level=_current_level(state),
                    tier_max=state.tier_max if state else "E0",
                    mastery=_mastery_estimate(state),
                    evidence_ids=evidence_ids,
                )
            )

    # -- learning objectives: one per root gap (the actionable frontier) -----
    objectives: list[LearningObjective] = []
    for s in sorted(root_gaps):
        from_status = raw_status[s]
        objective_type = "probe" if from_status == UNVERIFIED else "lesson"
        prereq_objective_ids = [
            objective_id_for(role_id, p) for p in hard_parents[s] if p in root_gaps
        ]
        if objective_type == "probe":
            # Verify-before-teach (Phase 5 brief): resolve what the learner
            # actually knows before scheduling any lesson content.
            acceptance_criteria = {
                "probe_items": 2,
                "resolves_to": "MET_or_WEAK",
                "note": "verify-before-teach: claimed/inferred only, no assessed or artifact evidence yet",
            }
        else:
            acceptance_criteria = {
                "assessed_items": 3,
                "mastery_threshold": LEVEL_MASTERY_THRESHOLD[req_level[s]],
            }
        objectives.append(
            LearningObjective(
                objective_id=objective_id_for(role_id, s),
                skill_id=s,
                from_status=from_status,
                objective_type=objective_type,
                target_level=req_level[s],
                priority=priority[s],
                prerequisite_objective_ids=prereq_objective_ids,
                acceptance_criteria=acceptance_criteria,
                reason_ref=f"gap:{role_id}:{s}",
            )
        )
    objectives.sort(key=lambda o: o.priority, reverse=True)

    prerequisite_edges = [(p, s) for s in scope for p in hard_parents[s]]

    return GapAnalysisResult(
        role_id=role_id,
        graph_version=graph.graph_version,
        scope_skill_ids=scope,
        gaps=sorted(gaps, key=lambda g: g.skill_id),
        strengths=sorted(strengths, key=lambda s: s.skill_id),
        audit_flags=audit_flags,
        objectives=objectives,
        layers=layers,
        prerequisite_edges=prerequisite_edges,
    )


def _compute_audit_flags(
    scope: set[str],
    state_by_skill: dict[str, LearnerSkillRecord],
    all_state_by_skill: dict[str, LearnerSkillRecord],
    req_level: dict[str, int],
    weights: dict[str, int],
    graph: SkillGraphService,
) -> list[AuditFlag]:
    """design §12.4's three flag types. Deterministic rule checks only --
    disputing a flag (`POST /skills/{id}/dispute`, design §12.4) is a later
    phase's endpoint; this only ever *emits* flags, never suppresses one a
    dispute hasn't actually resolved (flags are "never silently overridden")."""
    flags: list[AuditFlag] = []

    # (a) claimed_without_evidence / (c) stale_or_weak_evidence: both are
    # relative to *this role's* weight/required level, so scope-restricted.
    for s in sorted(scope):
        state = state_by_skill.get(s)
        if state is None:
            continue

        if state.tier_max == "E0" and weights.get(s, 0) >= 2:
            flags.append(
                AuditFlag(
                    flag_type="claimed_without_evidence",
                    skill_id=s,
                    message=f"{s} is self-reported only (no supporting evidence) but weighted important+ for this role.",
                )
            )

        if state.tier_max == "E1" and req_level.get(s, 1) >= 2:
            flags.append(
                AuditFlag(
                    flag_type="stale_or_weak_evidence",
                    skill_id=s,
                    message=f"{s} only has documented (E1) evidence but the role requires level {req_level[s]}.",
                )
            )

    # (b) claim_evidence_mismatch: a claim on a PART_OF parent while evidence
    # covers only some of its children (e.g. "Full Stack" with evidence for
    # "React" only, none for backend/database). Parents are usually umbrella
    # nodes outside `scope` (see the call site's comment), so this scans
    # every claimed skill graph-wide; children are still restricted to
    # `scope` so the flag only names gaps relevant to the current role.
    for s in sorted(all_state_by_skill):
        try:
            children = graph.part_of_children(s)
        except UnknownSkillError:
            # Evidence recorded against a skill_id no longer in the current
            # graph version (e.g. a re-ingested catalog dropped/renamed it)
            # -- skip rather than crash the whole report over stale data.
            continue
        children_in_scope = [c for c in children if c in scope]
        if not children_in_scope:
            continue
        covered = [c for c in children_in_scope if c in all_state_by_skill]
        uncovered = [c for c in children_in_scope if c not in all_state_by_skill]
        if covered and uncovered:
            flags.append(
                AuditFlag(
                    flag_type="claim_evidence_mismatch",
                    skill_id=s,
                    message=(
                        f"{s} is claimed, and evidence covers {covered}, "
                        f"but not {uncovered} -- do not assume the whole area is covered."
                    ),
                    related_skill_ids=covered + uncovered,
                )
            )

    return flags
