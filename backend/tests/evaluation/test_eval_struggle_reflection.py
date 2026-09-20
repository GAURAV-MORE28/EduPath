"""Evaluation: struggle classification, reflection validity and adaptation events (design §32.2 rows
"Struggle detection", "Intervention", "Re-plan quality").

Simulated learners with *injected* ground truth (design §32.1): a misconception planted in the answers,
a missing prerequisite, an item set that is simply too hard, self-reported overload -- plus benign
learners (one slip, too few items, a merely *suspected* misconception, a strong run) that must never
trigger an intervention. The Struggle Classifier is scored on primary-cause accuracy; the full
Reflection pipeline is run through the real API for every curated misconception that the item bank can
actually surface, and scored on root-cause correctness, validity and false-positive rate.
"""
from __future__ import annotations

import random

import pytest
from sqlalchemy import select

from app.assessment.struggle import (
    COGNITIVE_OVERLOAD,
    EXCESSIVE_DIFFICULTY,
    MISSING_PREREQUISITE,
    REPEATED_MISCONCEPTION,
    ItemOutcome,
    StruggleContext,
    classify_struggle,
    primary_signal,
)
from app.db import models as m
from app.db.session import SessionLocal
from app.repositories.catalog_repository import CatalogRepository
from tests.evaluation.metrics import record

pytestmark = pytest.mark.asyncio


# -- the classifier, against injected ground truth ----------------------------------------------------------------------------


def _items(rng, skill, n, *, wrong, tag=None, difficulty="medium", prefix="i"):
    picks = set(rng.sample(range(n), wrong))
    return [
        ItemOutcome(item_id=f"{prefix}.{skill}.{k}", skill_id=skill, difficulty=difficulty, correct=k not in picks, misconception_id=tag if k in picks else None)
        for k in range(n)
    ]


def _scenario(rng: random.Random, truth: str):
    """Returns (items, context, expected_details) for one simulated learner whose injected truth is `truth`."""
    T, P = "skill.target", "skill.prereq"
    if truth == REPEATED_MISCONCEPTION:
        m_id = rng.choice(["misc.a", "misc.b", "misc.c"])
        items = _items(rng, T, rng.randint(4, 6), wrong=rng.randint(2, 3), tag=m_id)
        return items, StruggleContext(skill_id=T, hard_prerequisite_status={P: "MET"}, misconception_root_skill={m_id: P}), {"misconception": m_id}
    if truth == MISSING_PREREQUISITE:
        items = _items(rng, T, 4, wrong=rng.randint(1, 2)) + _items(rng, P, 2, wrong=2, prefix="p")
        return items, StruggleContext(skill_id=T, hard_prerequisite_status={P: rng.choice(["WEAK", "MISSING", "UNVERIFIED"])}), {"prerequisite": P}
    if truth == EXCESSIVE_DIFFICULTY:
        items = _items(rng, T, 3, wrong=rng.randint(2, 3), difficulty="hard")
        return items, StruggleContext(skill_id=T, current_level=1, hard_prerequisite_status={P: "MET"}), {}
    if truth == COGNITIVE_OVERLOAD:
        items = _items(rng, T, 4, wrong=rng.randint(0, 1))
        return items, StruggleContext(skill_id=T, self_reported_overload=True, retries_trend_rising=True, hard_prerequisite_status={P: "MET"}), {}
    if truth == "one_slip":
        return _items(rng, T, 5, wrong=1), StruggleContext(skill_id=T, hard_prerequisite_status={P: "MET"}, mastery_estimate=0.8, n_obs=6), {}
    if truth == "too_few_items":
        # two misses on items *at* the learner's level: too little evidence for low_score (< 3 items) and not
        # "above level" for excessive_difficulty. (Two misses ABOVE level is excessive_difficulty by design §19.2.)
        return _items(rng, T, 2, wrong=2, difficulty="easy"), StruggleContext(skill_id=T, current_level=2, hard_prerequisite_status={P: "MET"}, mastery_estimate=0.6, n_obs=6), {}
    if truth == "suspected_misconception":
        return _items(rng, T, 4, wrong=1, tag="misc.a"), StruggleContext(skill_id=T, hard_prerequisite_status={P: "MET"}, mastery_estimate=0.7, n_obs=6), {}
    if truth == "strong":
        return _items(rng, T, 5, wrong=0), StruggleContext(skill_id=T, hard_prerequisite_status={P: "MET"}, mastery_estimate=0.9, n_obs=8), {}
    raise AssertionError(truth)


POSITIVE = [REPEATED_MISCONCEPTION, MISSING_PREREQUISITE, EXCESSIVE_DIFFICULTY, COGNITIVE_OVERLOAD]
BENIGN = ["one_slip", "too_few_items", "suspected_misconception", "strong"]


async def test_struggle_classifier_primary_cause_accuracy_and_zero_false_positive_interventions():
    rng = random.Random(20260920)
    N = 25
    confusion: dict[str, dict[str, int]] = {}
    root_ok = root_total = 0
    for truth in POSITIVE + BENIGN:
        for _ in range(N):
            items, ctx, details = _scenario(rng, truth)
            signals = classify_struggle(items, ctx)
            primary = primary_signal(signals)
            predicted = primary.signal_class if primary else "none"
            confusion.setdefault(truth, {})
            confusion[truth][predicted] = confusion[truth].get(predicted, 0) + 1
            if truth == MISSING_PREREQUISITE:
                root_total += 1
                root_ok += bool(primary) and primary.counts.get("prerequisite_skill_id") == details["prerequisite"]
            if truth == REPEATED_MISCONCEPTION:
                root_total += 1
                root_ok += bool(primary) and primary.counts.get("misconception_id") == details["misconception"]

    # the classes are scored one by one
    for cls in POSITIVE:
        recall = confusion[cls].get(cls, 0) / N
        predicted_cls = sum(confusion[t].get(cls, 0) for t in confusion)
        precision = confusion[cls].get(cls, 0) / predicted_cls if predicted_cls else 1.0
        record("Struggle", f"{cls}: recall / precision (primary cause)", f"{recall:.2f} / {precision:.2f}", "high", f"{N} simulated learners per class")
        assert recall >= 0.95, (cls, confusion[cls])
        assert precision >= 0.95, (cls, {t: confusion[t] for t in confusion})
    false_positives = sum(v for truth in BENIGN for pred, v in confusion[truth].items() if pred != "none")
    benign_total = N * len(BENIGN)
    record("Struggle", "false-positive interventions on benign learners", false_positives, "0", f"{benign_total} benign learners: one slip / too few items / merely-suspected misconception / strong")
    record("Struggle", "root-cause attribution (injected prerequisite / misconception id)", root_ok / root_total, "1.00", f"{root_total} scenarios")
    assert false_positives == 0, {t: confusion[t] for t in BENIGN}
    assert root_ok == root_total


# -- the full Reflection pipeline, through the real API ------------------------------------------------------------------------


INTAKE = {"current_skills": ["Python"], "experience_summary": "", "target_role_id": "role.ml_engineer", "career_goal": "", "weekly_hours": 10}
CLOSED_OPERATOR_SET = {"INSERT_REMEDIATION", "DEFER", "REMOVE_DUPLICATE", "REPLACE_RESOURCE", "ADD_PROBE", "SPLIT_ACTIVITY"}


async def _misconception_cases():
    """(misconception, affected skill, root skill, the wrong-tagged picks the item bank can actually serve)."""
    async with SessionLocal() as session:
        catalog = CatalogRepository(session)
        misconceptions = (await session.execute(select(m.Misconception))).scalars().all()
        cases = []
        for mc in misconceptions:
            picks = []
            for skill_id in dict.fromkeys([mc.skill_id, mc.root_skill_id]):
                for item in await catalog.get_practice_items_for_skill(skill_id, purpose="practice"):
                    for idx, opt in enumerate(item.options):
                        if not opt["is_key"] and opt["misconception_id"] == mc.misconception_id:
                            picks.append((item.item_id, idx))
                            break
            cases.append((mc, picks))
        return cases


async def _submit_scenario(client, user: str, skill_id: str, wrong_picks: list[tuple[str, int]], extra_correct_skill: str | None = None):
    """A fresh learner who plans a week, then submits exactly `wrong_picks` (plus correct answers elsewhere)."""
    client.cookies.set("session", user)
    assert (await client.post("/api/learners", json=INTAKE)).status_code == 201
    assert (await client.post("/api/learners/me/plans", json={})).status_code == 200
    learner_id = (await client.get("/api/learners/me/profile")).json()["learner_id"]
    async with SessionLocal() as session:
        catalog = CatalogRepository(session)
        answers = [{"item_id": iid, "chosen_option": idx} for iid, idx in wrong_picks]
        item_ids = [iid for iid, _ in wrong_picks]
        if extra_correct_skill:
            for item in (await catalog.get_practice_items_for_skill(extra_correct_skill, purpose="practice"))[:2]:
                if item.item_id not in item_ids:
                    item_ids.append(item.item_id)
                    answers.append({"item_id": item.item_id, "chosen_option": next(i for i, o in enumerate(item.options) if o["is_key"])})
        ps = m.PracticeSession(learner_id=learner_id, skill_id=skill_id, purpose="practice", item_ids=item_ids)
        session.add(ps)
        await session.commit()
        set_id = ps.set_id
    resp = await client.post(f"/api/practice/{set_id}/submit", json={"answers": answers})
    assert resp.status_code == 200, resp.text
    return resp.json(), learner_id


async def test_reflection_finds_the_injected_root_cause_for_every_misconception_the_bank_can_surface(app_client):
    cases = await _misconception_cases()
    evaluated = correct_root = valid = 0
    wrong: list[str] = []
    skipped = 0
    async with SessionLocal() as session:
        ancestors_of = {}
        from app.graph.loader import GraphLoader
        from app.graph.queries import SkillGraphService

        graph = SkillGraphService(await GraphLoader(CatalogRepository(session)).load())
    for i, (mc, picks) in enumerate(cases):
        if len(picks) < 2:  # not enough distinct tagged distractors in the curated bank to *confirm* it
            skipped += 1
            continue
        body, learner_id = await _submit_scenario(app_client, f"refl-{i}", mc.skill_id, picks[:3])
        reflection = body["reflection"]
        evaluated += 1
        if reflection is None:
            wrong.append(f"{mc.misconception_id}: no reflection")
            continue
        root_ok = reflection["root_cause_skill_id"] == mc.root_skill_id
        correct_root += root_ok
        if not root_ok:
            wrong.append(f"{mc.misconception_id}: root {reflection['root_cause_skill_id']} != injected {mc.root_skill_id}")
        connected = reflection["root_cause_skill_id"] == mc.skill_id or reflection["root_cause_skill_id"] in graph.hard_ancestors(mc.skill_id)
        ops = {op["op"] for op in reflection["operators"]}
        ok = connected and ops <= CLOSED_OPERATOR_SET and ops and not reflection["needs_attention"] and reflection["plan_revision_id"] and reflection["decision_id"]
        valid += bool(ok)
        if not ok:
            wrong.append(f"{mc.misconception_id}: invalid reflection {reflection}")
    assert evaluated >= 3, "the bank must let the evaluation confirm several distinct misconceptions"
    record("Reflection", "correct root-cause node rate", correct_root / evaluated, ">= 0.9", f"{evaluated} confirmed misconceptions ({skipped} of {len(cases)} have < 2 tagged distractors in the bank)")
    record("Reflection", "revisions valid (graph-connected root, closed operator set, committed + decision recorded)", valid / evaluated, "1.00")
    assert valid == evaluated, wrong
    assert correct_root / evaluated >= 0.9, wrong


async def test_no_false_positive_reflections_on_benign_submissions(app_client):
    """design §32.2: false-positive reflections (reflecting on a single low score) ~ 0 by design."""
    rng = random.Random(11)
    async with SessionLocal() as session:
        catalog = CatalogRepository(session)
        skills = [s for s in ("skill.python", "skill.sql_fundamentals", "skill.docker", "skill.chain_rule", "skill.backpropagation", "skill.cnn")
                  if await catalog.get_practice_items_for_skill(s, purpose="practice")]
    trials = reflections = 0
    for i, skill_id in enumerate(skills * 2):
        async with SessionLocal() as session:
            items = await CatalogRepository(session).get_practice_items_for_skill(skill_id, purpose="practice")
        items = items[:5]
        untagged_wrong = lambda it: next((k for k, o in enumerate(it.options) if not o["is_key"] and not o["misconception_id"]), None)  # noqa: E731
        slip = rng.randrange(len(items))
        picks = []
        for k, it in enumerate(items):
            key_idx = next(j for j, o in enumerate(it.options) if o["is_key"])
            wrong_idx = untagged_wrong(it)
            picks.append((it.item_id, wrong_idx if (k == slip and wrong_idx is not None) else key_idx))
        body, _ = await _submit_scenario(app_client, f"benign-{i}", skill_id, picks)
        trials += 1
        reflections += body["reflection"] is not None
    record("Reflection", "false-positive reflection rate (a single untagged slip)", reflections / trials, "0", f"{trials} benign submissions")
    assert reflections == 0


async def test_adaptation_events_are_linked_revertible_and_cooled_down(app_client, demo_mode):
    await app_client.post("/api/demo/seed")
    before = (await app_client.get("/api/learners/me/plans/current")).json()
    attempt = await app_client.post("/api/demo/scripted-attempt")
    reflection = attempt.json()["reflection"]
    assert reflection["reflection_id"] and reflection["decision_id"] and reflection["plan_revision_id"]

    async with SessionLocal() as session:
        signal_ids = {s.signal_id for s in (await session.execute(select(m.StruggleSignal))).scalars().all()}
        rec = (await session.execute(select(m.ReflectionRecord))).scalar_one()
        dec = await session.get(m.DecisionRecord, reflection["decision_id"])
        rev = await session.get(m.PlanRevision, reflection["plan_revision_id"])
        step = (await session.execute(select(m.AgentStep).where(m.AgentStep.decision_id == reflection["decision_id"]))).scalar_one()
    assert rec.signal_id in signal_ids and rec.validated and rec.plan_revision_id == rev.revision_id
    assert dec.output_ref == rev.revision_id and dec.type == "reflection" and dec.evidence_ids
    assert rev.cause_type == "reflection" and rev.parent_revision_id is not None
    assert step.output_ref == rev.revision_id  # the trace step points at the same revision the decision explains

    # one-click revert restores exactly the pre-reflection week, as a *new* revision (history stays linear)
    plan_id = before["plan_id"]
    reverted = await app_client.post(f"/api/learners/me/plans/{plan_id}/revisions/{rev.revision_id}/revert")
    assert reverted.status_code == 200
    key = lambda p: sorted((i["type"], i["skill_id"], i["resource_id"]) for i in p["items"])  # noqa: E731 -- item ids are fresh per revision
    assert key(reverted.json()) == key(before) and reverted.json()["revision_no"] == 3

    # cooldown: the same struggle immediately again does not reflect twice on the same misconception
    revisions_before = len((await app_client.get("/api/learners/me/plans/current/revisions")).json())
    again = await app_client.post("/api/demo/scripted-attempt")
    assert again.status_code == 200
    revisions_after = len((await app_client.get("/api/learners/me/plans/current/revisions")).json())
    assert revisions_after == revisions_before, "cooldown prevents a second automatic revision"
    record("Adaptation", "events linked (signal -> reflection -> decision -> revision -> trace step), revert restores, cooldown holds", 1.0, "1.00")
