"""EvidenceCommitService tests (design §10.6's read/write matrix: "Evidence
Verifier / Normalizer ... writes Evidence, LearnerSkillState (E0-E2)").
Uses the plain `sqlite_session` fixture (no catalog ingestion needed — these
tests exercise the commit logic itself, not catalog-anchored normalization).
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.thresholds import EVIDENCE_TIER_PRIORS
from app.db.models import Evidence, LearnerSkillState, PendingClaim
from app.profiling.commit import EvidenceCommitService
from app.repositories.profiling_repository import ProfilingRepository
from app.schemas.profiling import ClaimDecision


async def _seed_pending_claim(session, **overrides) -> PendingClaim:
    defaults = dict(
        claim_id="claim-1",
        learner_id="learner-1",
        run_id="run-1",
        document_id=None,
        skill_label="Python",
        category="python",
        context_type="skills_list",
        claimed_level_cue=None,
        verbatim_span="Python",
        span_offsets={"start": 0, "end": 6},
        tier="E1",
        normalized_skill_id="skill.python",
        normalization_method="exact_alias",
        normalization_confidence=1.0,
        status="pending",
    )
    defaults.update(overrides)
    claim = PendingClaim(**defaults)
    session.add(claim)
    await session.flush()
    return claim


@pytest.mark.asyncio
async def test_confirm_creates_evidence_and_skill_state(sqlite_session):
    await _seed_pending_claim(sqlite_session)
    service = EvidenceCommitService(ProfilingRepository(sqlite_session))

    summary = await service.commit_confirmed_claims("learner-1", [ClaimDecision(claim_id="claim-1", action="confirm")])
    await sqlite_session.commit()

    assert summary.confirmed == 1
    assert len(summary.evidence_created) == 1

    evidence = (await sqlite_session.execute(select(Evidence))).scalar_one()
    assert evidence.skill_id == "skill.python"
    assert evidence.tier == "E1"
    assert evidence.verified is True

    state = (await sqlite_session.execute(select(LearnerSkillState))).scalar_one()
    assert state.tier_max == "E1"
    assert (state.alpha, state.beta) == EVIDENCE_TIER_PRIORS["E1"]
    assert state.band == "unknown"
    assert state.n_obs == 0


@pytest.mark.asyncio
async def test_remove_does_not_create_evidence(sqlite_session):
    await _seed_pending_claim(sqlite_session)
    service = EvidenceCommitService(ProfilingRepository(sqlite_session))

    summary = await service.commit_confirmed_claims("learner-1", [ClaimDecision(claim_id="claim-1", action="remove")])
    await sqlite_session.commit()

    assert summary.removed == 1
    assert summary.confirmed == 0
    evidence_rows = (await sqlite_session.execute(select(Evidence))).scalars().all()
    assert evidence_rows == []

    claim = (await sqlite_session.execute(select(PendingClaim))).scalar_one()
    assert claim.status == "removed"


@pytest.mark.asyncio
async def test_confirm_unmapped_claim_without_override_is_skipped(sqlite_session):
    await _seed_pending_claim(sqlite_session, normalized_skill_id=None, normalization_method="unmapped", normalization_confidence=0.0)
    service = EvidenceCommitService(ProfilingRepository(sqlite_session))

    summary = await service.commit_confirmed_claims("learner-1", [ClaimDecision(claim_id="claim-1", action="confirm")])
    await sqlite_session.commit()

    assert summary.skipped_no_skill == 1
    assert summary.confirmed == 0
    assert summary.evidence_created == []


@pytest.mark.asyncio
async def test_manual_skill_id_override_maps_an_unmapped_claim(sqlite_session):
    await _seed_pending_claim(sqlite_session, normalized_skill_id=None, normalization_method="unmapped", normalization_confidence=0.0)
    service = EvidenceCommitService(ProfilingRepository(sqlite_session))

    decision = ClaimDecision(claim_id="claim-1", action="edit", skill_id_override="skill.python")
    summary = await service.commit_confirmed_claims("learner-1", [decision])
    await sqlite_session.commit()

    assert summary.confirmed == 1
    evidence = (await sqlite_session.execute(select(Evidence))).scalar_one()
    assert evidence.skill_id == "skill.python"


@pytest.mark.asyncio
async def test_a_second_stronger_tier_evidence_upgrades_skill_state(sqlite_session):
    await _seed_pending_claim(sqlite_session, claim_id="claim-1", tier="E0")
    await _seed_pending_claim(sqlite_session, claim_id="claim-2", tier="E2", verbatim_span="Python", span_offsets={"start": 0, "end": 6})
    service = EvidenceCommitService(ProfilingRepository(sqlite_session))

    await service.commit_confirmed_claims(
        "learner-1", [ClaimDecision(claim_id="claim-1", action="confirm"), ClaimDecision(claim_id="claim-2", action="confirm")]
    )
    await sqlite_session.commit()

    state = (await sqlite_session.execute(select(LearnerSkillState))).scalar_one()
    assert state.tier_max == "E2"
    assert (state.alpha, state.beta) == EVIDENCE_TIER_PRIORS["E2"]


@pytest.mark.asyncio
async def test_a_weaker_tier_evidence_does_not_downgrade_skill_state(sqlite_session):
    await _seed_pending_claim(sqlite_session, claim_id="claim-1", tier="E2")
    await _seed_pending_claim(sqlite_session, claim_id="claim-2", tier="E0", verbatim_span="Python", span_offsets={"start": 0, "end": 6})
    service = EvidenceCommitService(ProfilingRepository(sqlite_session))

    await service.commit_confirmed_claims(
        "learner-1", [ClaimDecision(claim_id="claim-1", action="confirm"), ClaimDecision(claim_id="claim-2", action="confirm")]
    )
    await sqlite_session.commit()

    state = (await sqlite_session.execute(select(LearnerSkillState))).scalar_one()
    assert state.tier_max == "E2"  # unchanged by the later, weaker E0 evidence
    assert (state.alpha, state.beta) == EVIDENCE_TIER_PRIORS["E2"]
    # both pieces of evidence are still recorded, even though only the stronger one drives the state
    evidence_rows = (await sqlite_session.execute(select(Evidence))).scalars().all()
    assert len(evidence_rows) == 2


@pytest.mark.asyncio
async def test_unknown_claim_id_is_ignored_not_erroring(sqlite_session):
    service = EvidenceCommitService(ProfilingRepository(sqlite_session))
    summary = await service.commit_confirmed_claims("learner-1", [ClaimDecision(claim_id="ghost", action="confirm")])
    assert summary.confirmed == 0
    assert summary.removed == 0
    assert summary.evidence_created == []


@pytest.mark.asyncio
async def test_claim_belonging_to_another_learner_is_ignored(sqlite_session):
    await _seed_pending_claim(sqlite_session, learner_id="learner-OTHER")
    service = EvidenceCommitService(ProfilingRepository(sqlite_session))
    summary = await service.commit_confirmed_claims("learner-1", [ClaimDecision(claim_id="claim-1", action="confirm")])
    assert summary.confirmed == 0
    assert summary.evidence_created == []


@pytest.mark.asyncio
async def test_already_confirmed_claim_is_not_reprocessed(sqlite_session):
    await _seed_pending_claim(sqlite_session, status="confirmed")
    service = EvidenceCommitService(ProfilingRepository(sqlite_session))
    summary = await service.commit_confirmed_claims("learner-1", [ClaimDecision(claim_id="claim-1", action="confirm")])
    assert summary.confirmed == 0
    assert summary.evidence_created == []
