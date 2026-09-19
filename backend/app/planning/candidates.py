"""Candidate building for the Planner (design §16.3 point 2: "Candidates:
for each objective, the Retriever supplies top-K resources plus
practice/probe candidates"). Orchestration glue -- fetches real `Resource`/
`PracticeItem` rows via the already-implemented Resource Retriever/Ranker
(Phase 6) and `CatalogRepository`, and assembles one `ObjectiveCandidateSet`
per `LearningObjective` (Gap Engine, Phase 4). No LLM here; this is exactly
the pre-built, ID-only candidate set the Planner Agent reads from
(ARCHITECTURE_CONTRACTS.md §7: "an LLM never emits a raw URL or invents an
ID; it selects from a pre-built candidate ID set").
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.core.thresholds import DEFAULT_SESSION_CAP_MINUTES, PROBE_ITEM_COUNT
from app.gap.engine import MET, GapAnalysisResult
from app.repositories.catalog_repository import CatalogRepository
from app.retrieval.ranker import ResourceUsageRecord
from app.retrieval.service import ResourceRetrievalService


@dataclass(frozen=True)
class ResourceCandidateInfo:
    """A ranked, eligible resource candidate with the metadata
    (title/url/type/duration/modality) the Planner and Fallback Planner need
    to schedule and explain it -- the Ranker's own `ResourceRecommendation`
    (`app/retrieval/ranker.py`) deliberately carries only the ID, score
    breakdown and eligibility flags, not resource metadata."""

    resource_id: str
    title: str
    url: str
    type: str
    duration_min: int
    modality: str
    score: float
    score_breakdown: dict[str, float]


@dataclass
class ObjectiveCandidateSet:
    """The candidate set one `LearningObjective` gets handed to the Planner
    Agent (draft/patch) and the Fallback Planner. `resources` is already
    ranked best-first (design §15.3) and eligibility-filtered (design
    §14.3 point 2) by the Retriever; `practice_item_ids` are curated
    `PracticeItem`s (design §11.3's `ASSESSES` edge) matching the
    objective's purpose (`probe` for verify-before-teach, `practice`
    otherwise, design §13.5/§18.1)."""

    objective_id: str
    skill_id: str
    objective_type: str  # "probe" | "lesson"
    target_level: int
    current_level: int
    priority: float
    prerequisite_objective_ids: list[str]
    resources: list[ResourceCandidateInfo] = field(default_factory=list)
    practice_item_ids: list[str] = field(default_factory=list)


async def build_candidate_sets(
    *,
    gap_result: GapAnalysisResult,
    retrieval_service: ResourceRetrievalService,
    catalog: CatalogRepository,
    modality_order: list[str] | None = None,
    language: str = "",
    session_cap_minutes: int = DEFAULT_SESSION_CAP_MINUTES,
    excluded_modalities: set[str] | None = None,
    learner_history: list[ResourceUsageRecord] | None = None,
    top_k: int = 5,
) -> dict[str, ObjectiveCandidateSet]:
    """One `ObjectiveCandidateSet` per `gap_result.objectives` entry, keyed
    by `objective_id`. Never invents a resource/practice-item ID: resources
    come from `ResourceRetrievalService.recommend_for_skill` (Phase 6,
    already graph-anchored to real `TARGETS` edges); practice items come
    from `CatalogRepository.get_practice_items_for_skill` (real `ASSESSES`
    edges). An objective with nothing eligible gets an empty candidate set,
    never a fabricated one -- both the Fallback Planner
    (`app/planning/fallback.py`) and the Plan Validator
    (`app/planning/validator.py`) already treat "no candidates" as "skip
    this objective this week", not an error (this is also how the required
    "impossible candidate set" case behaves: nothing to schedule, still a
    valid -- empty -- plan)."""
    current_level_by_skill = {g.skill_id: g.current_level for g in gap_result.gaps}
    met_skill_ids = {g.skill_id for g in gap_result.gaps if g.status == MET}

    candidate_sets: dict[str, ObjectiveCandidateSet] = {}
    for objective in gap_result.objectives:
        current_level = current_level_by_skill.get(objective.skill_id, 0)

        resources: list[ResourceCandidateInfo] = []
        if objective.objective_type == "lesson":
            recommendations = await retrieval_service.recommend_for_skill(
                skill_id=objective.skill_id,
                objective_id=objective.objective_id,
                current_level=current_level,
                met_skill_ids=met_skill_ids,
                modality_order=modality_order,
                language=language,
                session_cap_minutes=session_cap_minutes,
                excluded_modalities=excluded_modalities,
                learner_history=learner_history,
                top_k=top_k,
            )
            if recommendations:
                resource_rows = {
                    r.resource_id: r
                    for r in await catalog.get_resources_by_ids([rec.resource_id for rec in recommendations])
                }
                for rec in recommendations:
                    row = resource_rows.get(rec.resource_id)
                    if row is None:
                        continue  # stale ID (re-ingested catalog dropped it) -- skip, never invent
                    resources.append(
                        ResourceCandidateInfo(
                            resource_id=row.resource_id,
                            title=row.title,
                            url=row.url,
                            type=row.type,
                            duration_min=row.duration_min,
                            modality=row.modality,
                            score=rec.score,
                            score_breakdown=rec.score_breakdown,
                        )
                    )

        purpose = "probe" if objective.objective_type == "probe" else "practice"
        practice_items = await catalog.get_practice_items_for_skill(objective.skill_id, purpose=purpose)
        practice_item_ids = [it.item_id for it in practice_items]
        if objective.objective_type == "probe":
            practice_item_ids = practice_item_ids[:PROBE_ITEM_COUNT]

        candidate_sets[objective.objective_id] = ObjectiveCandidateSet(
            objective_id=objective.objective_id,
            skill_id=objective.skill_id,
            objective_type=objective.objective_type,
            target_level=objective.target_level,
            current_level=current_level,
            priority=objective.priority,
            prerequisite_objective_ids=list(objective.prerequisite_objective_ids),
            resources=resources,
            practice_item_ids=practice_item_ids,
        )

    return candidate_sets
