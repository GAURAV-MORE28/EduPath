"""Learner intake + document/evidence endpoints (design §27).

`learner_id` is always resolved from the session via `get_current_learner_id`
(ARCHITECTURE_CONTRACTS.md §7) — never accepted from the request body. These
routes are the API-layer half of G1 Onboarding (design §9.3); the actual
graph lives in `app/orchestration/graphs.py`, invoked via
`app/profiling/onboarding.py`.
"""
from __future__ import annotations

import uuid

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_learner_id, get_current_user_id
from app.db.models import Document, LearnerProfile
from app.db.session import get_session
from app.gateway.embedding_gateway import get_embedding_gateway
from app.gateway.llm_gateway import LLMGateway
from app.gateway.vlm_gateway import get_vlm_gateway
from app.profiling.commit import EvidenceCommitService
from app.profiling.document_parser import (
    CorruptDocumentError,
    DocumentTooLargeError,
    UnsupportedDocumentError,
    validate_upload,
)
from app.profiling.github_client import GitHubClient, InvalidGitHubUrlError
from app.profiling.onboarding import run_document_onboarding
from app.profiling.skill_normalizer import SkillNormalizer
from app.profiling.storage import DocumentStorage
from app.repositories.catalog_repository import CatalogRepository
from app.repositories.profiling_repository import ProfilingRepository
from app.repositories.user_repository import UserRepository
from app.schemas.profiling import (
    ClaimConfirmationInput,
    ConfirmationSummary,
    DocumentUploadResponse,
    IntakeRequest,
    LearnerProfileOut,
    PendingClaimOut,
    SpanOffsets,
    UnmappedSkill,
)
from app.schemas.profiling import ExtractedClaim as ExtractedClaimSchema
from app.schemas.profiling import VerifiedClaim as VerifiedClaimSchema

router = APIRouter(prefix="/learners", tags=["learners"])


# -- Intake -----------------------------------------------------------------


@router.post("", response_model=LearnerProfileOut, status_code=status.HTTP_201_CREATED)
async def create_learner_profile(
    body: IntakeRequest,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> LearnerProfileOut:
    catalog = CatalogRepository(session)
    profiling_repo = ProfilingRepository(session)

    role = await catalog.get_role(body.target_role_id)
    if role is None:
        # ARCHITECTURE_CONTRACTS.md §5: "If a requested role is not in the curated
        # graph: return 'role not supported'. Never invent a graph at runtime."
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="role not supported")

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
                learner_id=str(uuid.uuid4()),
                user_id=user_id,
                target_role_id=body.target_role_id,
                career_goal=body.career_goal,
                experience_summary=body.experience_summary,
                weekly_hours=body.weekly_hours,
                preferences=body.preferences.model_dump(),
                constraints=body.constraints,
            )
        )

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


# -- Documents ----------------------------------------------------------------


@router.post("/me/documents", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile | None = File(default=None),
    github_url: str | None = Form(default=None),
    learner_id: str = Depends(get_current_learner_id),
    session: AsyncSession = Depends(get_session),
) -> DocumentUploadResponse:
    if (file is None) == (github_url is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Provide exactly one of: file, github_url"
        )

    document_id = str(uuid.uuid4())
    llm_gateway = LLMGateway()
    embedding_gateway = get_embedding_gateway()
    vlm_gateway = get_vlm_gateway()

    if file is not None:
        content = await file.read()
        try:
            doc_type = validate_upload(file.filename or "upload", content)
        except (UnsupportedDocumentError, DocumentTooLargeError, CorruptDocumentError) as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

        storage_ref = DocumentStorage().save(learner_id, document_id, file.filename or "upload", content)
        document = Document(document_id=document_id, learner_id=learner_id, type=doc_type, storage_ref=storage_ref, parse_status="pending")
        await ProfilingRepository(session).create_document(document)

        summary, parse_status, text_hash = await run_document_onboarding(
            session=session,
            learner_id=learner_id,
            document_id=document_id,
            doc_type=doc_type,
            raw_content=content,
            llm_gateway=llm_gateway,
            embedding_gateway=embedding_gateway,
            vlm_gateway=vlm_gateway,
        )
    else:
        try:
            async with httpx.AsyncClient(timeout=10.0) as http_client:
                repo_summary = await GitHubClient(http_client).repo_summary(github_url)
        except InvalidGitHubUrlError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

        document = Document(document_id=document_id, learner_id=learner_id, type="github", storage_ref=github_url, parse_status="pending")
        await ProfilingRepository(session).create_document(document)

        summary_text = _build_github_summary_text(repo_summary)
        summary, parse_status, text_hash = await run_document_onboarding(
            session=session,
            learner_id=learner_id,
            document_id=document_id,
            doc_type="github",
            github_summary_text=summary_text,
            is_github_source=True,
            llm_gateway=llm_gateway,
            embedding_gateway=embedding_gateway,
            vlm_gateway=vlm_gateway,
        )
        if not repo_summary.fetched:
            parse_status = f"degraded: {repo_summary.degraded_reason}"

    document.parse_status = parse_status
    document.text_hash = text_hash
    await session.commit()

    return DocumentUploadResponse(
        document_id=document_id, run_id=summary.run_id, parse_status=parse_status, claims_summary=summary
    )


def _build_github_summary_text(repo_summary) -> str:
    if not repo_summary.fetched:
        return ""
    languages = ", ".join(repo_summary.languages.keys())
    parts = [
        f"GitHub repository {repo_summary.full_name}.",
        f"Description: {repo_summary.description}" if repo_summary.description else "",
        f"Languages used: {languages}." if languages else "",
        f"Dependency manifests present: {', '.join(repo_summary.manifest_files)}." if repo_summary.manifest_files else "",
        repo_summary.readme_excerpt,
    ]
    return "\n".join(p for p in parts if p)


# -- Pending claims / confirmation --------------------------------------------


@router.get("/me/claims/pending", response_model=list[PendingClaimOut])
async def get_pending_claims(
    learner_id: str = Depends(get_current_learner_id),
    session: AsyncSession = Depends(get_session),
) -> list[PendingClaimOut]:
    claims = await ProfilingRepository(session).list_pending_claims(learner_id)
    return [
        PendingClaimOut(
            claim_id=c.claim_id,
            skill_label=c.skill_label,
            category=c.category,
            context_type=c.context_type,
            claimed_level_cue=c.claimed_level_cue,
            verbatim_span=c.verbatim_span,
            span_offsets=SpanOffsets(**c.span_offsets),
            tier=c.tier,
            document_id=c.document_id,
            normalized_skill_id=c.normalized_skill_id,
            normalization_method=c.normalization_method,
            normalization_confidence=c.normalization_confidence,
        )
        for c in claims
    ]


@router.post("/me/claims/confirm", response_model=ConfirmationSummary)
async def confirm_claims(
    body: ClaimConfirmationInput,
    learner_id: str = Depends(get_current_learner_id),
    session: AsyncSession = Depends(get_session),
) -> ConfirmationSummary:
    service = EvidenceCommitService(ProfilingRepository(session))
    summary = await service.commit_confirmed_claims(learner_id, body.decisions)
    await session.commit()
    return summary
