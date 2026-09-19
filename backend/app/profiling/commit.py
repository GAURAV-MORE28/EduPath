"""Evidence commit — the deterministic write path for confirmed claims
(design §10.6's read/write matrix: "Evidence Verifier / Normalizer ... writes
Evidence, LearnerSkillState (E0-E2)"). Never called by the Profiler agent
directly (ARCHITECTURE_CONTRACTS.md §2/§13: agents don't mutate persisted
state) — only by the intake and claim-confirmation API routes, both of which
resolve `learner_id` from the session, never from client input
(ARCHITECTURE_CONTRACTS.md §7).
"""
from __future__ import annotations

from app.core.thresholds import EVIDENCE_TIER_PRIORS, TIER_ORDER
from app.db.models import Evidence, LearnerSkillState
from app.repositories.profiling_repository import ProfilingRepository
from app.schemas.profiling import ClaimDecision, ConfirmationSummary


class EvidenceCommitService:
    def __init__(self, repository: ProfilingRepository) -> None:
        self.repository = repository

    async def write_evidence(
        self,
        *,
        learner_id: str,
        skill_id: str,
        tier: str,
        source_type: str,
        span_text: str,
        span_offsets: dict | None,
        document_id: str | None = None,
        extracted_by_run: str | None = None,
    ) -> Evidence:
        evidence = await self.repository.create_evidence(
            Evidence(
                learner_id=learner_id,
                skill_id=skill_id,
                tier=tier,
                source_type=source_type,
                document_id=document_id,
                span_text=span_text,
                span_offsets=span_offsets,
                extracted_by_run=extracted_by_run,
                verified=True,
            )
        )
        await self._upsert_skill_state(learner_id, skill_id, tier)
        return evidence

    async def commit_confirmed_claims(self, learner_id: str, decisions: list[ClaimDecision]) -> ConfirmationSummary:
        """Applies each decision to its `PendingClaim` (which must belong to
        `learner_id` — a claim_id for another learner is silently ignored,
        never trusted). `action="edit"` and a manual `skill_id_override` are
        the mechanism design §22.5 point 4 describes for mapping an
        `unmapped` claim by hand before confirming it.
        """
        confirmed = removed = skipped_no_skill = 0
        evidence_created: list[str] = []

        for decision in decisions:
            claim = await self.repository.get_pending_claim(learner_id, decision.claim_id)
            if claim is None or claim.status != "pending":
                continue  # unknown, foreign, or already-resolved claim_id -- ignore, don't trust blindly

            if decision.action == "remove":
                claim.status = "removed"
                removed += 1
                continue

            skill_id = decision.skill_id_override or claim.normalized_skill_id
            if skill_id is None:
                claim.status = "confirmed"  # the claim text stands, but nothing to attach evidence to
                skipped_no_skill += 1
                continue

            evidence = await self.write_evidence(
                learner_id=learner_id,
                skill_id=skill_id,
                tier=claim.tier,
                source_type="document" if claim.document_id else "intake",
                span_text=claim.verbatim_span,
                span_offsets=claim.span_offsets,
                document_id=claim.document_id,
                extracted_by_run=claim.run_id,
            )
            evidence_created.append(evidence.evidence_id)
            claim.status = "confirmed"
            confirmed += 1

        return ConfirmationSummary(
            confirmed=confirmed, removed=removed, skipped_no_skill=skipped_no_skill, evidence_created=evidence_created
        )

    async def _upsert_skill_state(self, learner_id: str, skill_id: str, tier: str) -> None:
        existing = await self.repository.get_learner_skill_state(learner_id, skill_id)
        if existing is None:
            alpha, beta = EVIDENCE_TIER_PRIORS.get(tier, EVIDENCE_TIER_PRIORS["E0"])
            self.repository.session.add(
                LearnerSkillState(
                    learner_id=learner_id,
                    skill_id=skill_id,
                    alpha=alpha,
                    beta=beta,
                    band="unknown",  # n_obs = 0: no assessed items yet, design §10.4
                    confidence="low",
                    n_obs=0,
                    tier_max=tier,
                )
            )
            return

        if TIER_ORDER.index(tier) > TIER_ORDER.index(existing.tier_max):
            existing.tier_max = tier
            existing.alpha, existing.beta = EVIDENCE_TIER_PRIORS.get(tier, EVIDENCE_TIER_PRIORS["E0"])
        # else: a weaker/equal-tier evidence never downgrades an already-stronger skill state.
