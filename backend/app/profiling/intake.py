"""Learner intake + file-document ingestion services.

Extracted from `app/api/v1/learners.py` (Phase 12) so the HTTP routes and the
DEMO_MODE seeder (`app/demo/service.py`) run the *same* real code path:
self-reported skills become E0 evidence through the Skill Normalizer, and an
uploaded resume goes through validation -> storage -> the G1 onboarding graph.
No behavior change from the original route bodies.
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, LearnerProfile
from app.gateway.embedding_gateway import EmbeddingGateway, get_embedding_gateway
from app.gateway.llm_gateway import LLMGateway
from app.gateway.vlm_gateway import VLMGateway
from app.observability.context import bind_identity
from app.profiling.commit import EvidenceCommitService
from app.profiling.document_parser import validate_upload
from app.profiling.onboarding import run_document_onboarding
from app.profiling.skill_normalizer import SkillNormalizer
from app.profiling.storage import DocumentStorage
from app.repositories.catalog_repository import CatalogRepository
from app.repositories.profiling_repository import ProfilingRepository
from app.repositories.user_repository import UserRepository
from app.schemas.profiling import (
    DocumentUploadResponse,
    IntakeRequest,
    LearnerProfileOut,
    SpanOffsets,
    UnmappedSkill,
)
from app.schemas.profiling import ExtractedClaim as ExtractedClaimSchema
from app.schemas.profiling import VerifiedClaim as VerifiedClaimSchema


class UnsupportedRoleForIntakeError(Exception):
    """The requested role is not in the curated graph (never invent one at runtime)."""


async def apply_intake(
    session: AsyncSession, user_id: str, body: IntakeRequest, *, learner_id: str | None = None
) -> LearnerProfileOut:
    catalog = CatalogRepository(session)
    profiling_repo = ProfilingRepository(session)

    role = await catalog.get_role(body.target_role_id)
    if role is None:
        raise UnsupportedRoleForIntakeError(body.target_role_id)

    # LearnerProfile FK-references users.user_id; the session boundary's dev-mode
    # fallback (app/api/deps.py) has no real signup flow behind it yet, so ensure
    # a row exists rather than fail the FK constraint (see UserRepository.get_or_create).
    await UserRepository(session).get_or_create(user_id)

    existing = await profiling_repo.get_learner_profile_by_user_id(user_id)
    if existing is not None:
        existing.target_role_id = body.target_role_id
        existing.career_goal = body.career_goal
        existing.experience_summary = body.experience_summary
        existing.weekly_hours = body.weekly_hours
        existing.preferences = body.preferences.model_dump()
        existing.constraints = body.constraints
        profile = existing
    else:
        profile = await profiling_repo.create_learner_profile(
            LearnerProfile(
                learner_id=learner_id or str(uuid.uuid4()),
                user_id=user_id,
                target_role_id=body.target_role_id,
                career_goal=body.career_goal,
                experience_summary=body.experience_summary,
                weekly_hours=body.weekly_hours,
                preferences=body.preferences.model_dump(),
                constraints=body.constraints,
            )
        )

    bind_identity(learner_id=profile.learner_id)
    skills = await catalog.get_all_skills()
    normalizer = SkillNormalizer(skills, get_embedding_gateway(), LLMGateway())
    commit_service = EvidenceCommitService(profiling_repo)

    mapped_count = 0
    unmapped: list[UnmappedSkill] = []
    for label in body.current_skills:
        label = label.strip()
        if not label:
            continue
        claim = ExtractedClaimSchema(
            label=label,
            category="",
            context_type="skills_list",
            claimed_level_cue=None,
            verbatim_span=label,
            source_doc_id="intake",
            span_offsets=SpanOffsets(start=0, end=len(label)),
        )
        # Self-reported intake fields are structured form input, not text pulled from a
        # document -- there is nothing to span-verify against, so this is trivially "verified".
        verified = VerifiedClaimSchema(claim=claim, tier="E0", span_verified=True, injection_flagged=False)
        normalized = await normalizer.normalize(verified)
        if normalized.skill_id is None:
            unmapped.append(UnmappedSkill(label=label, reason="no confident catalog match"))
            continue
        await commit_service.write_evidence(
            learner_id=profile.learner_id,
            skill_id=normalized.skill_id,
            tier="E0",
            source_type="intake",
            span_text=label,
            span_offsets={"start": 0, "end": len(label)},
        )
        mapped_count += 1

    await session.commit()

    return LearnerProfileOut(
        learner_id=profile.learner_id,
        target_role_id=profile.target_role_id,
        career_goal=profile.career_goal,
        experience_summary=profile.experience_summary,
        weekly_hours=profile.weekly_hours,
        preferences=profile.preferences,
        constraints=profile.constraints,
        mapped_skill_count=mapped_count,
        unmapped_skills=unmapped,
    )




async def ingest_file_document(
    session: AsyncSession,
    learner_id: str,
    filename: str,
    content: bytes,
    *,
    llm_gateway: LLMGateway,
    embedding_gateway: EmbeddingGateway | None = None,
    vlm_gateway: VLMGateway,
) -> DocumentUploadResponse:
    """Validate (raises the `document_parser` upload errors), store, and run the
    G1 onboarding graph over one uploaded file. Commits."""
    doc_type = validate_upload(filename, content)
    document_id = str(uuid.uuid4())
    storage_ref = DocumentStorage().save(learner_id, document_id, filename, content)
    document = Document(document_id=document_id, learner_id=learner_id, type=doc_type, storage_ref=storage_ref, parse_status="pending")
    await ProfilingRepository(session).create_document(document)
    summary, parse_status, text_hash = await run_document_onboarding(
        session=session,
        learner_id=learner_id,
        document_id=document_id,
        doc_type=doc_type,
        raw_content=content,
        llm_gateway=llm_gateway,
        embedding_gateway=embedding_gateway or get_embedding_gateway(),
        vlm_gateway=vlm_gateway,
    )
    document.parse_status = parse_status
    document.text_hash = text_hash
    await session.commit()
    return DocumentUploadResponse(document_id=document_id, run_id=summary.run_id, parse_status=parse_status, claims_summary=summary)
