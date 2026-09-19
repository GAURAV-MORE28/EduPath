"""Reflection Validator tests (`app/reflection/validator.py`, design §20.6).
A small hand-built graph (mirrors `tests/test_resolution.py`'s
`_graph_service`), not the full curated dataset -- isolates exactly the five
checks this module owns. The wow-scenario end-to-end path (real curated
`skill.chain_rule`/`skill.backpropagation`) is covered by
`tests/test_reflection_service.py`.
"""
from __future__ import annotations

from app.assessment.struggle import StruggleSignalEntry
from app.db.models import Misconception, Resource, Role, RoleRequirement, Skill, SkillEdge
from app.gap.engine import MISSING, SkillGapEntry
from app.graph.loader import GraphLoader
from app.graph.queries import SkillGraphService
from app.reflection.draft import ReflectionDraft
from app.reflection.evidence import EvidenceBundle
from app.reflection.validator import validate_reflection
from app.repositories.catalog_repository import CatalogSnapshot
from app.schemas.common import PlanItem, PlanItemReason


def _graph_service() -> SkillGraphService:
    snapshot = CatalogSnapshot(
        skills=[
            Skill(skill_id="skill.a", label="A", kind="concept", area="test", aliases=[], description="", assessable=True),
            Skill(skill_id="skill.b", label="B", kind="concept", area="test", aliases=[], description="", assessable=True),
            Skill(skill_id="skill.c", label="C", kind="concept", area="test", aliases=[], description="", assessable=True),
        ],
        skill_edges=[
            SkillEdge(from_skill="skill.a", to_skill="skill.b", type="PREREQUISITE_OF", strength="hard", min_level=1, weight=None, source="curated", reviewed_by="test"),
        ],
        roles=[Role(role_id="role.test", title="Test", description="")],
        role_requirements=[RoleRequirement(role_id="role.test", skill_id="skill.b", required_level=2, weight=3)],
        misconceptions=[
            Misconception(misconception_id="misc.x", description="", skill_id="skill.b", root_skill_id="skill.a", signature="", severity="high", remediation_candidates=["res.remedy"]),
        ],
        resources=[
            Resource(resource_id="res.remedy", title="Remedy", url="https://example.org/r", provider="test", type="article", difficulty=1, duration_min=15, modality="read", prerequisite_skill_ids=[], learning_objective_text="", audience="", language="en", cost="free", curation_tier="curated", reviewed_by="test", link_status="ok"),
        ],
        resource_skills=[],
        practice_items=[],
        graph_meta=None,
    )
    return SkillGraphService(GraphLoader.build(snapshot))


def _gap(skill_id: str, *, status: str = MISSING, current_level: int = 0) -> SkillGapEntry:
    return SkillGapEntry(skill_id=skill_id, label=skill_id, status=status, gap_type=status.lower(), required_level=2, current_level=current_level)


def _signal(*, skill_id="skill.b", signal_class="missing_prerequisite", evidence_ids=("item.1",), counts=None) -> StruggleSignalEntry:
    return StruggleSignalEntry(
        signal_class=signal_class, skill_id=skill_id, confidence="high", evidence_ids=list(evidence_ids),
        counts=counts or {"prerequisite_skill_id": "skill.a"}, signal_id="signal-1",
    )


def _bundle(**overrides) -> EvidenceBundle:
    defaults = dict(
        learner_id="learner-1",
        struggling_skill_id="skill.b",
        triggering_signal=_signal(),
        all_signals=[_signal()],
        misconception_id=None,
        misconception_root_skill_id=None,
        ancestor_statuses={"skill.a": MISSING},
        graph_version="v-test",
        current_plan_items=[
            PlanItem(item_id="i1", type="resource", objective_id="obj.b", skill_id="skill.b", resource_id="res.other", est_minutes=30, difficulty=1, day_slot=1, reason=PlanItemReason()),
        ],
        learner_assessment_item_ids=frozenset({"item.1", "item.2"}),
        weekly_hours_budget_minutes=600.0,
    )
    defaults.update(overrides)
    return EvidenceBundle(**defaults)


def _draft(**overrides) -> ReflectionDraft:
    defaults = dict(
        root_cause_class="missing_prerequisite",
        root_cause_skill_id="skill.a",
        misconception_id=None,
        evidence_ids=["item.1"],
        hypothesis="h",
        confidence="high",
        path_decision="patch",
        operators=[
            {"op": "DEFER", "params": {"skill_id": "skill.b"}},
            {"op": "INSERT_REMEDIATION", "params": {"skill_id": "skill.a", "resource_ids": ["res.remedy"]}},
            {"op": "ADD_PROBE", "params": {"skill_id": "skill.a", "purpose": "resolution-check", "practice_item_ids": ["p1"]}},
        ],
    )
    defaults.update(overrides)
    return ReflectionDraft(**defaults)


def _validate(draft, bundle, *, new_skill_cap=3):
    graph = _graph_service()
    gaps_by_skill = {"skill.a": _gap("skill.a"), "skill.b": _gap("skill.b")}
    hard_prereqs_by_skill = {"skill.a": [], "skill.b": ["skill.a"]}
    return validate_reflection(draft, bundle, graph=graph, gaps_by_skill=gaps_by_skill, hard_prereqs_by_skill=hard_prereqs_by_skill, new_skill_cap=new_skill_cap)


def test_a_valid_ancestor_root_cause_with_supporting_evidence_is_approved():
    result = _validate(_draft(), _bundle())
    assert result.approved, result.reasons
    assert result.apply_result is not None
    assert any(i.skill_id == "skill.a" and i.type == "review" for i in result.apply_result.items)


def test_root_cause_must_be_self_or_an_ancestor():
    result = _validate(_draft(root_cause_skill_id="skill.c"), _bundle())
    assert not result.approved
    assert any("neither" in r for r in result.reasons)


def test_root_cause_may_be_the_struggling_skill_itself():
    # no pre-existing skill.b lesson item here -- isolates this check from
    # V3_prerequisite_order (skill.a, skill.b's hard prerequisite, is MISSING
    # in this fixture, which the *other* tests' pre-existing skill.b item
    # deliberately doesn't need to satisfy since its root cause is skill.a).
    draft = _draft(root_cause_skill_id="skill.b", operators=[
        {"op": "INSERT_REMEDIATION", "params": {"skill_id": "skill.b", "resource_ids": ["res.remedy"]}},
        {"op": "ADD_PROBE", "params": {"skill_id": "skill.b", "purpose": "resolution-check", "practice_item_ids": ["p1"]}},
    ])
    result = _validate(draft, _bundle(current_plan_items=[]))
    assert result.approved, result.reasons


def test_unknown_root_cause_skill_is_rejected():
    result = _validate(_draft(root_cause_skill_id="skill.does_not_exist"), _bundle())
    assert not result.approved
    assert any("not a known skill" in r for r in result.reasons)


def test_evidence_not_belonging_to_the_learner_is_rejected():
    result = _validate(_draft(evidence_ids=["item.not_mine"]), _bundle())
    assert not result.approved
    assert any("assessment history" in r for r in result.reasons)


def test_empty_evidence_is_rejected():
    result = _validate(_draft(evidence_ids=[]), _bundle())
    assert not result.approved


def test_evidence_must_overlap_the_triggering_signal():
    # item.2 belongs to the learner, but the triggering signal's own evidence is item.1.
    result = _validate(_draft(evidence_ids=["item.2"]), _bundle())
    assert not result.approved
    assert any("do not overlap" in r for r in result.reasons)


def test_class_mismatch_with_the_classifier_is_rejected_classifier_wins():
    result = _validate(_draft(root_cause_class="excessive_difficulty"), _bundle())
    assert not result.approved
    assert any("classifier wins" in r for r in result.reasons)


def test_operator_outside_the_closed_set_is_rejected():
    result = _validate(_draft(operators=[{"op": "DELETE_EVERYTHING", "params": {}}]), _bundle())
    assert not result.approved
    assert any("closed operator set" in r for r in result.reasons)


def test_operator_with_missing_params_is_rejected():
    result = _validate(_draft(operators=[{"op": "DEFER", "params": {}}]), _bundle())
    assert not result.approved


def test_resulting_plan_must_pass_hard_validation():
    # a budget far too small for the inserted remediation + probe items.
    result = _validate(_draft(), _bundle(weekly_hours_budget_minutes=1.0))
    assert not result.approved
    assert result.plan_validation is not None
    assert not result.plan_validation.passed
