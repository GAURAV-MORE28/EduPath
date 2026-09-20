"""Resource sessionization (Stage 2): the deterministic *planning unit* derived from a real catalog resource.

Why this exists: the Resource Retriever used to drop every resource longer than the learner's session cap, and the Planner could
only schedule a resource as one indivisible block, so large weekly budgets stayed mostly empty (see
`docs/RESOURCE_SESSIONIZATION.md` §1). A `ResourceSession` lets the Planner schedule *part* of a long resource -- one sitting --
while staying tied to the real resource it came from.

Design rules (pure module: no DB, no gateway, no LLM -- same shape as `app/planning/validator.py`):

* A session is **derived**, never invented. Its id is `"<resource_id>#<n>"` and the only things it adds to the resource are
  arithmetic on the resource's own `duration_min` (segment length, nominal position). The catalog has no chapter/module
  metadata, so segments carry a neutral label ("<title> — Study Segment 2 of 8") and `start_min`/`end_min` are the *nominal
  minute range of the resource's estimated duration*, not real chapter boundaries.
* A resource that fits one session (`duration <= max_session_minutes`) is a single **complete** session (count 1, label = title).
  It is never split, however short.
* A longer resource is divided into `ceil(duration / max)` segments of near-equal length (sizes differ by at most one minute).
  Every segment is `<= max_session_minutes` and, by construction, `>= max_session_minutes // 2`, hence never absurdly small.
  `min_session_minutes` is enforced as `min(min_session_minutes, max_session_minutes // 2)` so a small learner cap stays feasible.
* Segmentation is a function of `(duration, policy)` only, so a validator can recompute it independently of whoever proposed a plan.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from app.core.thresholds import DEFAULT_SESSION_CAP_MINUTES, SESSION_MAX_MINUTES, SESSION_MIN_MINUTES


@dataclass(frozen=True)
class SessionizationPolicy:
    """Configurable segmentation thresholds. `max_session_minutes` is normally the learner's own session length."""

    max_session_minutes: int = DEFAULT_SESSION_CAP_MINUTES
    min_session_minutes: int = SESSION_MIN_MINUTES

    @classmethod
    def for_learner(cls, session_cap_minutes: int, *, min_session_minutes: int = SESSION_MIN_MINUTES) -> "SessionizationPolicy":
        """The learner's cap, bounded to `[1, SESSION_MAX_MINUTES]`."""
        cap = max(1, min(int(session_cap_minutes or DEFAULT_SESSION_CAP_MINUTES), SESSION_MAX_MINUTES))
        return cls(max_session_minutes=cap, min_session_minutes=min_session_minutes)

    @property
    def effective_min_minutes(self) -> int:
        return max(1, min(self.min_session_minutes, self.max_session_minutes // 2))


@dataclass(frozen=True)
class ResourceSession:
    """One study sitting drawn from one real resource. Carries the resource's identifying metadata so it can be shown and
    audited without a second lookup, but the resource row stays the source of truth for it."""

    session_id: str
    resource_id: str
    index: int  # 1-based position within the resource
    count: int  # number of sessions the whole resource divides into
    est_minutes: int
    start_min: int  # nominal position in the resource's estimated duration (NOT a chapter boundary)
    end_min: int
    resource_duration_min: int  # the original, unsplit duration
    label: str
    title: str = ""
    provider: str = ""
    url: str = ""
    modality: str = ""
    resource_type: str = ""
    difficulty: int = 1
    skill_id: str = ""  # the objective's skill this candidate was generated for (a TARGETS edge)
    curation_tier: str = ""
    provenance: str = "catalog"  # only catalog rows are sessionized; web results never reach this module

    @property
    def is_complete_resource(self) -> bool:
        return self.count == 1


@dataclass(frozen=True)
class SessionMeta:
    """The provenance stored on a plan item (`app.schemas.common.PlanItemSession` mirrors this)."""

    session_id: str
    resource_id: str
    index: int
    count: int
    label: str
    start_min: int
    end_min: int
    resource_duration_min: int


def make_session_id(resource_id: str, index: int) -> str:
    return f"{resource_id}#{index}"


def segment_durations(duration_min: int, policy: SessionizationPolicy) -> list[int]:
    """Minutes of each session, in order. `[]` for a non-positive duration (nothing to study)."""
    if duration_min <= 0:
        return []
    cap = max(1, policy.max_session_minutes)
    if duration_min <= cap:
        return [duration_min]
    n = math.ceil(duration_min / cap)
    # n = ceil(d / cap) with d > cap makes every segment >= cap // 2 >= effective_min_minutes (proved in the docstring and
    # property-tested in tests/test_resource_sessions.py), so the minimum never forces a merge that would break the hard cap.
    base, extra = divmod(duration_min, n)
    return [base + 1] * extra + [base] * (n - extra)


def sessionize_resource(
    *,
    resource_id: str,
    title: str,
    duration_min: int,
    policy: SessionizationPolicy,
    provider: str = "",
    url: str = "",
    modality: str = "",
    resource_type: str = "",
    difficulty: int = 1,
    skill_id: str = "",
    curation_tier: str = "",
) -> tuple[ResourceSession, ...]:
    """All sessions of one resource, in study order. Deterministic; never invents metadata."""
    durations = segment_durations(duration_min, policy)
    count = len(durations)
    sessions: list[ResourceSession] = []
    start = 0
    for i, minutes in enumerate(durations, start=1):
        sessions.append(
            ResourceSession(
                session_id=make_session_id(resource_id, i),
                resource_id=resource_id,
                index=i,
                count=count,
                est_minutes=minutes,
                start_min=start,
                end_min=start + minutes,
                resource_duration_min=duration_min,
                label=title if count == 1 else f"{title} — Study Segment {i} of {count}",
                title=title,
                provider=provider,
                url=url,
                modality=modality,
                resource_type=resource_type,
                difficulty=difficulty,
                skill_id=skill_id,
                curation_tier=curation_tier,
            )
        )
        start += minutes
    return tuple(sessions)


def session_meta(session: ResourceSession) -> SessionMeta:
    return SessionMeta(
        session_id=session.session_id,
        resource_id=session.resource_id,
        index=session.index,
        count=session.count,
        label=session.label,
        start_min=session.start_min,
        end_min=session.end_min,
        resource_duration_min=session.resource_duration_min,
    )
