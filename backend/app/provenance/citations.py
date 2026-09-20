"""Citation verification (design §14.5, §23.2, §24; ARCHITECTURE_CONTRACTS.md
§2's "Tutor ... cannot mutate ... citation verifier").

Pure, deterministic, no LLM/DB import -- the same "unit-testable with
hand-built fixtures" shape as `app/gap/engine.py`/`app/reflection/validator.py`.
The Tutor Agent's answer is untrusted output (design §26.3's trust zone T3)
until every ID it cites is checked against the pool of IDs the caller actually
handed it as context this turn (`valid_ids` -- built by
`app/tutor/service.py` from the real tool-call results, never from the LLM's
own claims about what it saw). An empty `citations` list on a non-empty
answer is treated as a failure too: design §23.3's "numbers and statuses come
from tool outputs" implies every factual answer must name at least one
source, not merely avoid naming a fake one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass(frozen=True)
class CitationCheckResult:
    passed: bool
    cited_ids: list[str] = field(default_factory=list)
    invalid_ids: list[str] = field(default_factory=list)  # cited but not in valid_ids
    reason: str = ""  # display/log only


def verify_citations(cited_ids: Sequence[str], valid_ids: set[str]) -> CitationCheckResult:
    """design §14.5: "They may reference only IDs present in their context."
    `valid_ids` is the union of every `ToolCallResult.citable_ids` collected
    during this chat turn's `call_tools` step -- an ID that was never surfaced
    by a tool this turn fails verification even if it is a real ID somewhere
    else in the database (design §23.3: "Not cached across learners" / every
    turn is re-grounded in its own fresh tool calls, never a prior turn's or
    another learner's).
    """
    cited = list(dict.fromkeys(cited_ids))  # de-duplicate, preserve order
    if not cited:
        return CitationCheckResult(passed=False, cited_ids=[], invalid_ids=[], reason="no citations")
    invalid = [cid for cid in cited if cid not in valid_ids]
    if invalid:
        return CitationCheckResult(passed=False, cited_ids=cited, invalid_ids=invalid, reason="uncited or invented id")
    return CitationCheckResult(passed=True, cited_ids=cited, invalid_ids=[])
