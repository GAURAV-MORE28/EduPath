"""DEMO_MODE: the seeded persona, deterministic scenario and rehearsal checks
(design §38, §38.3).

Nothing here fakes a result. The seeder drives the *same* services the API
routes use (intake -> resume ingestion -> claim confirmation -> plan) over the
curated demo files under `data/dataset/demo/`; the scripted attempt submits a
scripted set of answers through the real `submit_practice_set` (Struggle
Classifier -> Reflection -> validated plan revision). Only two things are
scripted, by design §38.3: *which answers* the demo learner picks (the
"scripted attempt" button, so no on-stage misclick) and *which persona* exists.

Answer keys never leave the server: the scripted attempt resolves option
indexes here, from the item bank, rather than shipping keys to a client.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.assessment.service import SubmitOutcome, SubmittedAnswer, submit_practice_set
from app.catalog.ingest import default_dataset_dir
from app.config import get_settings
from app.db import models as m
from app.gateway.embedding_gateway import get_embedding_gateway
from app.gateway.llm_gateway import LLMGateway
from app.gateway.vlm_gateway import get_vlm_gateway
from app.graph.queries import SkillGraphService
from app.observability.context import bind_identity
from app.planning.service import create_plan
from app.profiling.commit import EvidenceCommitService
from app.profiling.intake import apply_intake, ingest_file_document
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.catalog_repository import CatalogRepository
from app.repositories.profiling_repository import ProfilingRepository
from app.schemas.profiling import ClaimDecision, IntakeRequest

DEMO_LEARNER_ID = "demo-learner-asha"


class DemoDisabledError(Exception):
    """DEMO_MODE is off: the demo endpoints refuse to run."""


class DemoScenarioError(Exception):
    """The curated scenario no longer matches the item bank (a data bug, reported loudly)."""


def _demo_dir() -> Path:
    return default_dataset_dir() / "demo"


def load_scenario() -> dict[str, Any]:
    return json.loads((_demo_dir() / "demo_scenario.json").read_text(encoding="utf-8"))


def load_demo_learner() -> dict[str, Any]:
    return json.loads((_demo_dir() / "demo_learner.json").read_text(encoding="utf-8"))


def load_demo_resume() -> bytes:
    return (_demo_dir() / "demo_resume.md").read_bytes()


def require_demo_mode() -> None:
    if not get_settings().demo_mode:
        raise DemoDisabledError("DEMO_MODE is not enabled")


@dataclass
class DemoSeedResult:
    learner_id: str
    user_id: str
    role_id: str
    claims_extracted: int
    claims_confirmed: int
    evidence_ids: list[str] = field(default_factory=list)
    plan_id: str | None = None
    plan_item_count: int = 0
    scenario_id: str = ""
    seeded_skills: list[str] = field(default_factory=list)


def load_demo_learner_state() -> dict[str, Any]:
    return json.loads((_demo_dir() / "demo_learner_state.json").read_text(encoding="utf-8"))


async def apply_seeded_state(session: AsyncSession, learner_id: str, known_skill_ids: set[str]) -> list[str]:
    """Write the persona's pre-seeded evidence-graded state (`demo_learner_state.json`,
    design §38.1: "seeded data") into the real `Evidence` / `LearnerSkillState` tables.

    The seeded rows stand in for what a cached GitHub fetch + a prior week of practice would
    have produced; each carries its curated note as the evidence span and a `demo_seed`
    source type, so the trace/UI can always tell seeded evidence from the live resume's.
    Returns the skill ids that were seeded. Skills unknown to the catalog are skipped."""
    repo = ProfilingRepository(session)
    commit = EvidenceCommitService(repo)
    seeded: list[str] = []
    for state in load_demo_learner_state()["skill_states"]:
        skill_id = state["skill_id"]
        if skill_id not in known_skill_ids or state.get("tier_max") is None:
            continue  # MISSING skills have nothing to seed
        notes = [e["note"] for e in state.get("evidence", [])] or state.get("claims", [])
        for note in notes[:1]:
            await commit.write_evidence(
                learner_id=learner_id, skill_id=skill_id, tier=state["tier_max"], source_type="demo_seed",
                span_text=note, span_offsets=None,
            )
        row = await repo.get_learner_skill_state(learner_id, skill_id)
        if row is not None:
            mastery = state["mastery"]
            row.alpha, row.beta = float(mastery["alpha"]), float(mastery["beta"])
            row.band, row.confidence, row.n_obs = mastery["band"].lower(), mastery["confidence"], int(mastery["n_obs"])
            row.tier_max = state["tier_max"]
        seeded.append(skill_id)
    await session.flush()
    return seeded


async def erase_learner_data(session: AsyncSession, learner_id: str) -> None:
    """Delete every row owned by `learner_id` (demo reset; also the building block a
    future `DELETE /learners/me` needs). Explicit FK-safe order -- the plan tables have a
    circular reference (`weekly_plans.current_revision_id` <-> `plan_revisions.plan_id`)."""
    plan_ids = select(m.WeeklyPlan.plan_id).where(m.WeeklyPlan.learner_id == learner_id)
    await session.execute(delete(m.AgentStep).where(m.AgentStep.learner_id == learner_id))
    await session.execute(delete(m.AgentRun).where(m.AgentRun.learner_id == learner_id))
    await session.execute(delete(m.ReflectionRecord).where(m.ReflectionRecord.learner_id == learner_id))
    await session.execute(delete(m.DecisionRecord).where(m.DecisionRecord.learner_id == learner_id))
    await session.execute(update(m.WeeklyPlan).where(m.WeeklyPlan.learner_id == learner_id).values(current_revision_id=None))
    await session.execute(delete(m.PlanItem).where(m.PlanItem.plan_id.in_(plan_ids)))
    await session.execute(delete(m.PlanRevision).where(m.PlanRevision.plan_id.in_(plan_ids)))
    await session.execute(delete(m.WeeklyPlan).where(m.WeeklyPlan.learner_id == learner_id))
    for model in (m.LearnerMisconception, m.Assessment, m.StruggleSignal, m.PracticeSession, m.PendingClaim, m.Evidence, m.LearnerSkillState, m.Document):
        await session.execute(delete(model).where(model.learner_id == learner_id))
    await session.execute(delete(m.LearnerProfile).where(m.LearnerProfile.learner_id == learner_id))
    await session.flush()


async def seed_demo_learner(
    session: AsyncSession, graph_service: SkillGraphService, *, user_id: str, llm_gateway: LLMGateway | None = None
) -> DemoSeedResult:
    """Reset and re-create the demo persona ("Asha", design §38.1) for `user_id`."""
    require_demo_mode()
    llm_gateway = llm_gateway or LLMGateway()
    scenario = load_scenario()
    learner = load_demo_learner()
    profiling_repo = ProfilingRepository(session)

    # The persona has one fixed learner_id (replay hashes stay stable across rehearsals):
    # free it if this user -- or any other user -- currently holds it, and drop this
    # user's own previous profile.
    for existing in (await profiling_repo.get_learner_profile_by_user_id(user_id), await profiling_repo.get_learner_profile(DEMO_LEARNER_ID)):
        if existing is not None:
            await erase_learner_data(session, existing.learner_id)
    await session.commit()

    intake = IntakeRequest(
        current_skills=["Python", "PyTorch", "OpenCV"],
        experience_summary=learner["experience_summary"],
        target_role_id=learner["target_role_id"],
        career_goal=learner["career_goal"],
        weekly_hours=learner["weekly_hours"],
        preferences={"modality_order": learner["preferences"]["modality_order"], "language": "en", "session_length_min": 60},
        constraints=learner.get("constraints", {}),
    )
    profile = await apply_intake(session, user_id, intake, learner_id=DEMO_LEARNER_ID)
    bind_identity(user_id=user_id, learner_id=profile.learner_id)

    upload = await ingest_file_document(
        session, profile.learner_id, "demo_resume.md", load_demo_resume(),
        llm_gateway=llm_gateway, embedding_gateway=get_embedding_gateway(), vlm_gateway=get_vlm_gateway(),
    )

    pending = await profiling_repo.list_pending_claims(profile.learner_id)
    decisions = [ClaimDecision(claim_id=c.claim_id, action="confirm") for c in pending if c.normalized_skill_id]
    decisions += [ClaimDecision(claim_id=c.claim_id, action="remove") for c in pending if not c.normalized_skill_id]
    summary = await EvidenceCommitService(profiling_repo).commit_confirmed_claims(profile.learner_id, decisions)
    seeded_skills = await apply_seeded_state(session, profile.learner_id, {sk.skill_id for sk in await CatalogRepository(session).get_all_skills()})
    await session.commit()

    plan = await create_plan(
        session=session, graph_service=graph_service, llm_gateway=llm_gateway, embedding_gateway=get_embedding_gateway(),
        learner_id=profile.learner_id, role_id=profile.target_role_id, week_index=0, weekly_hours=profile.weekly_hours,
        modality_order=profile.preferences.get("modality_order"), language=profile.preferences.get("language", ""),
        session_cap_minutes=profile.preferences.get("session_length_min") or 45,
    )
    await session.commit()

    return DemoSeedResult(
        learner_id=profile.learner_id, user_id=user_id, role_id=profile.target_role_id,
        claims_extracted=upload.claims_summary.extracted,
        claims_confirmed=summary.confirmed, evidence_ids=summary.evidence_created,
        plan_id=plan.plan_id, plan_item_count=len(plan.items), scenario_id=scenario["scenario_id"],
        seeded_skills=seeded_skills,
    )


def _option_index(item: m.PracticeItem, *, chosen_is_key: bool, misconception_id: str | None) -> int:
    """Resolve a scripted answer to an option index, from the bank (keys never leave the server).
    A key answer is any `is_key` option (curated keys may carry a stray misconception tag --
    IMPLEMENTATION_STATE.md Phase 8 quirk). A wrong answer prefers the scripted misconception tag."""
    if chosen_is_key:
        for idx, option in enumerate(item.options):
            if option.get("is_key"):
                return idx
        raise DemoScenarioError(f"{item.item_id} has no key option")
    wrong = [(idx, option) for idx, option in enumerate(item.options) if not option.get("is_key")]
    if not wrong:
        raise DemoScenarioError(f"{item.item_id} has no wrong option")
    for idx, option in wrong:
        if misconception_id and option.get("misconception_id") == misconception_id:
            return idx
    # No wrong option carries the scripted tag for this item: still a wrong answer, never the key.
    return wrong[0][0]


async def run_scripted_attempt(
    session: AsyncSession, graph_service: SkillGraphService, *, learner_id: str, llm_gateway: LLMGateway | None = None
) -> SubmitOutcome:
    """The "scripted attempt" button (design §38.2 step 8): submit the scenario's wrong
    answers for the seeded backpropagation set + chain-rule prerequisite block through the
    real submit path. Returns the real `SubmitOutcome` (signals, reflection, revision)."""
    require_demo_mode()
    scenario = load_scenario()
    scripted = scenario["scripted_attempt"]["answers"]
    catalog = CatalogRepository(session)

    items = {i.item_id: i for i in await catalog.get_practice_items_by_ids([a["item_id"] for a in scripted])}
    missing = [a["item_id"] for a in scripted if a["item_id"] not in items]
    if missing:
        raise DemoScenarioError(f"scenario items missing from the item bank: {missing}")

    answers = [
        SubmittedAnswer(
            item_id=a["item_id"],
            chosen_option=_option_index(items[a["item_id"]], chosen_is_key=bool(a["chosen_is_key"]), misconception_id=a.get("chosen_misconception_id")),
        )
        for a in scripted
    ]
    practice_session = m.PracticeSession(
        learner_id=learner_id, skill_id=scenario["seeded_misconception"]["affected_skill"], purpose="practice", item_ids=[a["item_id"] for a in scripted]
    )
    await AssessmentRepository(session).create_practice_session(practice_session)
    outcome = await submit_practice_set(
        session=session, graph=graph_service, llm_gateway=llm_gateway or LLMGateway(), learner_id=learner_id,
        set_id=practice_session.set_id, answers=answers,
    )
    await session.commit()
    return outcome


async def preflight(session: AsyncSession, graph_service: SkillGraphService | None) -> dict[str, Any]:
    """The design §38.3 rehearsal checklist as data: graph loaded, catalog and item bank
    present and consistent with the scenario, link status, replay cache, LLM mode."""
    settings = get_settings()
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    catalog = CatalogRepository(session)
    skills = await catalog.get_all_skills()
    add("graph_loaded", graph_service is not None and len(skills) > 0, f"{len(skills)} skills in the catalog" + ("" if graph_service else "; startup graph cache empty"))

    resources = (await session.execute(select(m.Resource))).scalars().all()
    broken = [r.resource_id for r in resources if r.link_status not in ("ok", "unchecked")]
    add("catalog_links", len(resources) > 0 and not broken, f"{len(resources)} resources, {len(broken)} with a non-ok link status")

    items = (await session.execute(select(m.PracticeItem))).scalars().all()
    add("item_bank", len(items) > 0, f"{len(items)} practice items")

    scenario_ok, scenario_detail = True, "scenario matches the item bank"
    try:
        scenario = load_scenario()
        wanted = {a["item_id"] for a in scenario["scripted_attempt"]["answers"]}
        have = {i.item_id for i in items}
        if wanted - have:
            scenario_ok, scenario_detail = False, f"scenario items missing from the bank: {sorted(wanted - have)}"
        if graph_service is not None and scenario["seeded_graph_path"][0] not in {s.skill_id for s in skills}:
            scenario_ok, scenario_detail = False, "scenario skills missing from the catalog"
    except Exception as exc:  # noqa: BLE001 -- a missing/corrupt scenario file is a failed check, not a crash
        scenario_ok, scenario_detail = False, f"scenario files unreadable: {type(exc).__name__}"
    add("demo_scenario", scenario_ok, scenario_detail)

    replay_entries = len((await session.execute(select(m.LlmReplayEntry.prompt_hash))).all())
    live = settings.llm_provider != "none"
    add(
        "llm_mode",
        True,
        f"provider={settings.llm_provider}, replay_mode={settings.replay_mode}, record={settings.llm_record or settings.demo_mode}, "
        f"{replay_entries} recorded responses" + ("" if live else " -- reduced-intelligence mode (deterministic agents)"),
    )
    add("demo_mode", settings.demo_mode, "DEMO_MODE on" if settings.demo_mode else "DEMO_MODE off (seed/scripted-attempt endpoints disabled)")

    return {
        "ready": all(c["ok"] for c in checks if c["name"] != "demo_mode"),
        "demo_mode": settings.demo_mode,
        "replay_mode": settings.replay_mode,
        "llm_provider": settings.llm_provider,
        "graph_version": graph_service.graph_version if graph_service is not None else None,
        "recorded_llm_responses": replay_entries,
        "checks": checks,
    }
