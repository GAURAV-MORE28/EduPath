"""The conservative, LLM-free answer (design §9.6: "If verification fails,
the answer is regenerated once... otherwise a conservative answer is
returned ('here is what the records show…')").

Built directly from the same tool-call results the LLM was given — not
narrated at all — so it is grounded by construction: every fact in it *is*
a raw ID/value from `ToolCallResult.data`, and its citations are exactly the
`citable_ids` of whichever tool calls actually returned data. This is also
what a fully degraded gateway (`LLM_PROVIDER=none`, this project's permanent
default) falls through to immediately, without spending a retry on a call
that will not succeed (the same "won't change on retry" reasoning
`app/reflection/service.py::_try_agent_rounds` already applies).
"""
from __future__ import annotations

from app.tutor.tools import ToolCallResult


def build_conservative_answer(tool_results: list[ToolCallResult]) -> tuple[str, list[str]]:
    usable = [r for r in tool_results if r.data]
    if not usable:
        return (
            "I don't have enough recorded information to answer that yet — try asking about your "
            "current plan, your skill gaps, or your progress.",
            [],
        )

    lines: list[str] = ["Here is what your records show:"]
    citations: list[str] = []
    for result in usable:
        lines.append(f"- {_summarize(result)}")
        citations.extend(sorted(result.citable_ids))

    return " ".join(lines), list(dict.fromkeys(citations))


def _summarize(result: ToolCallResult) -> str:
    data = result.data
    if result.tool == "get_gaps":
        gaps = data.get("gaps", [])
        open_gaps = [g for g in gaps if g["status"] != "MET"]
        return f"{len(open_gaps)} of {len(gaps)} role skills are not yet MET."
    if result.tool == "get_current_plan":
        if "plan" in data and data["plan"] is None:
            return "You don't have a plan yet."
        items = data.get("items", [])
        planned = [i for i in items if i["status"] == "planned"]
        return f"Your current plan (revision {data.get('revision_no')}) has {len(planned)} item(s) still planned."
    if result.tool == "get_revisions":
        revisions = data.get("revisions", [])
        return f"Your plan has {len(revisions)} revision(s) on record."
    if result.tool == "get_evidence":
        evidence = data.get("evidence", [])
        return f"{data.get('skill_id')} has {len(evidence)} evidence record(s) on file."
    if result.tool == "explain_skill_path":
        path = data.get("path")
        if not path:
            return f"{data.get('skill_id')} has no recorded prerequisite path to a role-required skill."
        chain = " -> ".join(step["label"] for step in path)
        return f"Prerequisite path: {chain}."
    if result.tool == "search_resources":
        resources = data.get("resources", [])
        return f"{len(resources)} catalog resource(s) found for {data.get('skill_id')}."
    if result.tool == "get_progress":
        return (
            f"{len(data.get('acquired', []))} skill(s) acquired, "
            f"{len(data.get('in_progress', []))} in progress, "
            f"{len(data.get('remaining_gaps', []))} gap(s) remaining."
        )
    if result.tool == "get_decision":
        if not data.get("decision_id"):
            return "That decision record could not be found."
        return f"Decision {data.get('decision_id')} ({data.get('type')}) fired rules: {data.get('rules_fired')}."
    if result.tool == "get_learner_state":
        return f"You are tracking {len(data.get('skills', {}))} skill(s) toward {data.get('target_role_id')}."
    return f"{result.tool} returned data."
