"""Async orchestration for the Resource Retriever/Ranker: fetches real
catalog rows (`CatalogRepository`, `SkillGraphService`), computes the query
embedding (`EmbeddingGateway`), and calls into the pure pipeline
(`app/retrieval/ranker.py`). Mirrors `app/profiling/onboarding.py`'s split
between "pure algorithm" and "DB/gateway glue".
"""
from __future__ import annotations

from datetime import date

from app.core.thresholds import DEFAULT_SESSION_CAP_MINUTES
from app.gateway.embedding_gateway import EmbeddingGateway
from app.graph.queries import SkillGraphService
from app.repositories.catalog_repository import CatalogRepository
from app.retrieval.ranker import ResourceCandidate, ResourceRecommendation, ResourceUsageRecord, recommend


class ResourceRetrievalService:
    def __init__(
        self,
        catalog: CatalogRepository,
        graph: SkillGraphService,
        embedding_gateway: EmbeddingGateway,
    ) -> None:
        self.catalog = catalog
        self.graph = graph
        self.embedding_gateway = embedding_gateway

    async def _candidates_for_skill(self, skill_id: str) -> list[ResourceCandidate]:
        pairs = await self.catalog.get_resources_targeting_skill(skill_id)
        return [
            ResourceCandidate(
                resource_id=resource.resource_id,
                title=resource.title,
                url=resource.url,
                provider=resource.provider,
                type=resource.type,
                duration_min=resource.duration_min,
                modality=resource.modality,
                prerequisite_skill_ids=list(resource.prerequisite_skill_ids or []),
                learning_objective_text=resource.learning_objective_text,
                language=resource.language,
                curation_tier=resource.curation_tier,
                last_verified_at=resource.last_verified_at,
                link_status=resource.link_status,
                embedding=list(resource.embedding) if resource.embedding is not None else None,
                level_from=resource_skill.level_from,
                level_to=resource_skill.level_to,
            )
            for resource, resource_skill in pairs
        ]

    async def recommend_for_skill(
        self,
        *,
        skill_id: str,
        objective_id: str | None = None,
        current_level: int = 0,
        met_skill_ids: set[str] | None = None,
        modality_order: list[str] | None = None,
        language: str = "",
        session_cap_minutes: int = DEFAULT_SESSION_CAP_MINUTES,
        excluded_modalities: set[str] | None = None,
        learner_history: list[ResourceUsageRecord] | None = None,
        top_k: int = 5,
        as_of: date | None = None,
    ) -> list[ResourceRecommendation]:
        """design §14.3's `anchor -> eligibility filter -> hybrid retrieval
        -> rank -> MMR` pipeline for one `(skill_id, target_level)` gap. The
        Planner (Phase 5, not yet implemented) will be the first real
        caller, once it exists to turn a `WeeklyPlan` scheduling decision
        into a call here per `LearningObjective`."""
        skill = self.graph.get_skill(skill_id)  # UnknownSkillError propagates -- never silently empty
        candidates = await self._candidates_for_skill(skill_id)
        if not candidates:
            return []

        query_text = f"{skill.label}. {skill.description}" if skill.description else skill.label
        query_embedding = await self.embedding_gateway.embed(query_text)

        return recommend(
            skill_id=skill_id,
            objective_id=objective_id,
            current_level=current_level,
            candidates=candidates,
            query_embedding=query_embedding,
            query_text=query_text,
            met_skill_ids=met_skill_ids,
            modality_order=modality_order,
            language=language,
            session_cap_minutes=session_cap_minutes,
            excluded_modalities=excluded_modalities,
            learner_history=learner_history,
            top_k=top_k,
            as_of=as_of,
        )
