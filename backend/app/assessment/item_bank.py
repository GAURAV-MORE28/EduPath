"""Practice-set assembly (design §18.2): item-bank-first, generate-if-short,
and the prerequisite-block rule. Async orchestration -- touches the catalog
and (when the bank is short) the Assessor Agent; same orchestration role as
`app/retrieval/service.py` (not a pure module, unlike `app/gap/engine.py`).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.agents.assessor import AssessorAgent
from app.core.thresholds import PRACTICE_SET_PREREQ_BLOCK_MIN_ITEMS, PRACTICE_SET_TARGET_SIZE
from app.db.models import Misconception, PracticeItem
from app.gap.engine import UNVERIFIED
from app.graph.queries import SkillGraphService
from app.repositories.catalog_repository import CatalogRepository

# design §18.2's "Select target: (skill, level, purpose)" -- a plain-language
# level label for the generation prompt, not a graph/DB concept.
LEVEL_LABELS: dict[int, str] = {0: "beginner / not yet assessed", 1: "foundational", 2: "working", 3: "proficient"}


@dataclass
class AssembledSet:
    skill_id: str
    purpose: str
    item_ids: list[str] = field(default_factory=list)
    misconception_id: str | None = None  # set for a resolution-check set targeting one specific misconception


async def assemble_practice_set(
    *,
    catalog: CatalogRepository,
    graph: SkillGraphService,
    assessor_agent: AssessorAgent,
    skill_id: str,
    current_level: int,
    purpose: str = "practice",
    gap_statuses: dict[str, str] | None = None,  # skill_id -> gap status, for the prerequisite-block rule
    seen_item_ids: set[str] | None = None,
    target_size: int = PRACTICE_SET_TARGET_SIZE,
    misconception_id: str | None = None,  # required when purpose == "resolution-check"
) -> AssembledSet:
    """design §18.2 points 1-3, 6. Never invents an item: bank items are
    real `PracticeItem` rows, and generated items (Assessor Agent, blind-
    solver-validated) are persisted to that same bank *before* their IDs are
    returned, so a caller can always resolve `item_ids` back to real rows.
    Returns fewer than `target_size` items if the bank is short and
    generation is unavailable (no LLM provider configured) or the Assessor
    Agent's blind-solver check rejects everything it proposed -- never an
    error, per this project's graceful-degradation posture.
    """
    seen = seen_item_ids or set()
    gap_statuses = gap_statuses or {}
    skill = graph.get_skill(skill_id)  # UnknownSkillError propagates -- never silently empty

    if purpose == "resolution-check":
        if misconception_id is None:
            raise ValueError("resolution-check requires a misconception_id")
        candidates = await catalog.get_practice_items_for_skill(skill_id, purpose="resolution-check")
        tagged = [it for it in candidates if _targets_misconception(it, misconception_id)]
        pool = tagged or candidates
        item_ids = [it.item_id for it in pool if it.item_id not in seen][:PRACTICE_SET_PREREQ_BLOCK_MIN_ITEMS]
        return AssembledSet(skill_id=skill_id, purpose=purpose, item_ids=item_ids, misconception_id=misconception_id)

    bank = [it for it in await catalog.get_practice_items_for_skill(skill_id, purpose=purpose) if it.item_id not in seen]
    item_ids = [it.item_id for it in bank[:target_size]]

    if len(item_ids) < target_size:
        misconceptions = await catalog.get_misconceptions_for_skill(skill_id)
        generated = await _generate_and_store(
            catalog=catalog,
            assessor_agent=assessor_agent,
            skill_id=skill_id,
            skill_label=skill.label,
            skill_description=skill.description,
            current_level=current_level,
            misconceptions=misconceptions,
            count=target_size - len(item_ids),
            graph_version=graph.graph_version,
        )
        item_ids.extend(g.item_id for g in generated)

    # prerequisite-block rule (design §18.2 point 6): if a hard prerequisite
    # is UNVERIFIED, append >= 2 items on it -- lets one sitting distinguish
    # "missing prerequisite" from "missing knowledge of this skill" (design
    # §13.4's chain-rule/backpropagation example).
    if purpose in ("practice", "probe"):
        for prereq in graph.direct_prerequisites(skill_id, include_soft=False):
            if gap_statuses.get(prereq) != UNVERIFIED:
                continue
            prereq_items = await catalog.get_practice_items_for_skill(prereq, purpose="prereq-block")
            if not prereq_items:
                prereq_items = await catalog.get_practice_items_for_skill(prereq, purpose="practice")
            for it in prereq_items[:PRACTICE_SET_PREREQ_BLOCK_MIN_ITEMS]:
                if it.item_id not in item_ids:
                    item_ids.append(it.item_id)

    return AssembledSet(skill_id=skill_id, purpose=purpose, item_ids=item_ids)


def _targets_misconception(item: PracticeItem, misconception_id: str) -> bool:
    return any(o.get("misconception_id") == misconception_id for o in item.options)


async def _generate_and_store(
    *,
    catalog: CatalogRepository,
    assessor_agent: AssessorAgent,
    skill_id: str,
    skill_label: str,
    skill_description: str,
    current_level: int,
    misconceptions: list[Misconception],
    count: int,
    graph_version: str,
) -> list[PracticeItem]:
    result = await assessor_agent.run(
        f"assessor-gen-{skill_id}",
        {
            "skill_label": skill_label,
            "skill_description": skill_description,
            "level_label": LEVEL_LABELS.get(current_level, str(current_level)),
            "misconceptions": [
                {"misconception_id": m.misconception_id, "description": m.description} for m in misconceptions
            ],
            "count": count,
        },
    )

    stored: list[PracticeItem] = []
    for draft in result["items"]:
        row = await catalog.create_practice_item(
            PracticeItem(
                item_id=f"item.generated.{uuid.uuid4()}",
                skill_id=skill_id,
                type="mcq",
                difficulty=draft["difficulty"],
                purpose="practice",
                stem=draft["question"],
                options=draft["options"],
                explanation=draft["explanation"],
                validated=True,  # blind-solver-validated (app/agents/assessor.py never returns an unvalidated item)
                generated_by="assessor-llm",
                validated_by="blind-solver",
                graph_version=graph_version,
            )
        )
        stored.append(row)
    return stored
