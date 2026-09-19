"""Unit tests for app/graph/validation.py's structural invariants (design
§11.5 step 4; ARCHITECTURE_CONTRACTS.md §5's build-time DAG invariant).
Uses small hand-built fixtures (not the real dataset) so each invariant can
be tested in isolation with a single, obvious violation.
"""
from __future__ import annotations

import copy

from app.graph.validation import GraphValidator


def _valid_dataset() -> dict:
    """A minimal, fully-valid catalog: skill.a -> skill.b (hard prereq),
    one role requiring skill.b, one resource targeting each skill, one
    misconception rooted in skill.a affecting skill.b, one well-formed item.
    """
    return {
        "skills": [
            {"skill_id": "skill.a", "label": "A", "assessable": True},
            {"skill_id": "skill.b", "label": "B", "assessable": True},
        ],
        "roles": [
            {"role_id": "role.x", "required_skills": [{"skill_id": "skill.b", "required_level": 1, "weight": 1}]}
        ],
        "edges": [
            {"from_skill": "skill.a", "to_skill": "skill.b", "type": "PREREQUISITE_OF", "strength": "hard"},
        ],
        "resources": [
            {
                "resource_id": "res.a",
                "skill_targets": [{"skill_id": "skill.a"}],
                "prerequisite_skill_ids": [],
                "url": "https://docs.python.org/a",
                "link_status": "ok",
            },
            {
                "resource_id": "res.b",
                "skill_targets": [{"skill_id": "skill.b"}],
                "prerequisite_skill_ids": [],
                "url": "https://docs.python.org/b",
                "link_status": "ok",
            },
        ],
        "misconceptions": [
            {
                "misconception_id": "misc.a",
                "affected_skill": "skill.b",
                "root_prerequisite": "skill.a",
                "remediation_candidates": ["res.a"],
            }
        ],
        "items": [
            {
                "item_id": "item.b.1",
                "skill_id": "skill.b",
                "options": [
                    {"text": "right", "is_key": True, "misconception_id": None},
                    {"text": "wrong", "is_key": False, "misconception_id": "misc.a"},
                ],
            }
        ],
    }


def _validate(dataset: dict):
    return GraphValidator().validate(
        skills=dataset["skills"],
        roles=dataset["roles"],
        edges=dataset["edges"],
        resources=dataset["resources"],
        misconceptions=dataset["misconceptions"],
        items=dataset["items"],
    )


def test_valid_dataset_has_no_errors():
    report = _validate(_valid_dataset())
    assert report.ok
    assert report.errors == []


def test_cycle_detection():
    dataset = _valid_dataset()
    # skill.b -> skill.a closes a hard-prerequisite cycle with skill.a -> skill.b
    dataset["edges"].append({"from_skill": "skill.b", "to_skill": "skill.a", "type": "PREREQUISITE_OF", "strength": "hard"})
    report = _validate(dataset)
    assert not report.ok
    assert any("cycle" in e for e in report.errors)


def test_soft_prerequisite_cycle_is_not_a_dag_violation():
    dataset = _valid_dataset()
    # A soft-strength back-edge must NOT trip the DAG check (only hard edges count).
    dataset["edges"].append({"from_skill": "skill.b", "to_skill": "skill.a", "type": "PREREQUISITE_OF", "strength": "soft"})
    report = _validate(dataset)
    assert report.ok


def test_missing_edge_reference_is_an_error():
    dataset = _valid_dataset()
    dataset["edges"].append({"from_skill": "skill.a", "to_skill": "skill.ghost", "type": "PREREQUISITE_OF", "strength": "hard"})
    report = _validate(dataset)
    assert not report.ok
    assert any("skill.ghost" in e for e in report.errors)


def test_duplicate_skill_id_is_an_error():
    dataset = _valid_dataset()
    dataset["skills"].append({"skill_id": "skill.a", "label": "dup", "assessable": True})
    report = _validate(dataset)
    assert not report.ok
    assert any("Duplicate skill id" in e for e in report.errors)


def test_orphan_skill_is_an_error():
    dataset = _valid_dataset()
    dataset["skills"].append({"skill_id": "skill.orphan", "label": "orphan", "assessable": False})
    report = _validate(dataset)
    assert not report.ok
    assert any("Orphan skill" in e and "skill.orphan" in e for e in report.errors)


def test_item_without_exactly_one_correct_option_is_an_error():
    dataset = _valid_dataset()
    dataset["items"][0]["options"] = [
        {"text": "a", "is_key": True, "misconception_id": None},
        {"text": "b", "is_key": True, "misconception_id": None},
    ]
    report = _validate(dataset)
    assert not report.ok
    assert any("exactly one correct option" in e for e in report.errors)


def test_role_required_skill_with_no_resources_is_a_warning_not_an_error():
    dataset = _valid_dataset()
    dataset["resources"] = [r for r in dataset["resources"] if r["resource_id"] != "res.b"]
    report = _validate(dataset)
    assert report.ok
    assert any("0 catalog resources" in w for w in report.warnings)


def test_misconception_root_not_an_ancestor_is_a_warning_not_an_error():
    dataset = _valid_dataset()
    # Point the root at an unrelated skill (still valid ref, just not an ancestor).
    dataset["skills"].append({"skill_id": "skill.unrelated", "label": "u", "assessable": True})
    dataset["resources"].append(
        {
            "resource_id": "res.u",
            "skill_targets": [{"skill_id": "skill.unrelated"}],
            "prerequisite_skill_ids": [],
            "url": "https://docs.python.org/u",
            "link_status": "ok",
        }
    )
    dataset["misconceptions"][0]["root_prerequisite"] = "skill.unrelated"
    report = _validate(dataset)
    assert report.ok
    assert any("not a hard-prerequisite ancestor" in w for w in report.warnings)


def test_malformed_url_is_an_error():
    dataset = _valid_dataset()
    dataset["resources"][0]["url"] = "ftp://not-https.example.com/a"
    report = _validate(dataset)
    assert not report.ok
    assert any("malformed/non-https" in e for e in report.errors)


def test_item_coverage_report_is_informational_not_an_error():
    dataset = _valid_dataset()
    report = _validate(dataset)
    assert report.ok
    assert "skill.a" in report.item_coverage["zero"]  # skill.a is assessable but has 0 items
    assert "skill.b" in report.item_coverage["under_six"]  # skill.b has exactly 1 item


def test_validate_does_not_mutate_input():
    dataset = _valid_dataset()
    snapshot = copy.deepcopy(dataset)
    _validate(dataset)
    assert dataset == snapshot
