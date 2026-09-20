"""Session / auth boundary.

ARCHITECTURE_CONTRACTS.md §7, §13: `learner_id` (and `user_id`) must always be
derived from the session/auth context, never accepted as a request-body or
LLM argument on learner-scoped endpoints. Phase 1 provides the dependency
shape (a signed session cookie) with a permissive dev default; real
authentication (sign-up/login) is out of scope until a phase requires it —
this only establishes the boundary so later routers cannot accidentally take
`learner_id` from the client.
"""
from __future__ import annotations

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_session
from app.graph.loader import GraphLoader
from app.graph.queries import SkillGraphService
from app.observability.context import bind_identity
from app.repositories.catalog_repository import CatalogRepository
from app.repositories.profiling_repository import ProfilingRepository


async def get_current_user_id(session: str | None = Cookie(default=None)) -> str:
    """Resolve the current user id from the session cookie.

    Dev-mode fallback (`session=dev-user`) is enabled only when `env=dev`, so
    the foundation layer's endpoints (health, docs) can be exercised without a
    full auth flow. Any learner-scoped router built in a later phase must
    reject missing sessions in non-dev environments.
    """
    settings = get_settings()
    if session is None:
        if settings.env == "dev":
            bind_identity(user_id="dev-user")
            return "dev-user"
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    bind_identity(user_id=session)
    return session


async def get_current_learner_id(
    user_id: str = Depends(get_current_user_id),
    db_session: AsyncSession = Depends(get_session),
) -> str:
    """Resolves `learner_id` for `/api/learners/me/...` routes
    (ARCHITECTURE_CONTRACTS.md §7: session-derived, never accepted as a
    request-body/LLM argument). Raises 404 if the current user hasn't
    completed intake (`POST /api/learners`) yet — there is no learner
    profile to attach documents/claims/evidence to."""
    profile = await ProfilingRepository(db_session).get_learner_profile_by_user_id(user_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No learner profile for this user yet — complete intake first"
        )
    bind_identity(learner_id=profile.learner_id)
    return profile.learner_id


async def get_skill_graph_service(
    request: Request,
    db_session: AsyncSession = Depends(get_session),
) -> SkillGraphService:
    """The Gap Engine's read-only view of the curated Skill Graph (Phase 3).

    Prefers the singleton loaded once at process startup (`app/main.py`'s
    lifespan, per ARCHITECTURE_CONTRACTS.md §5: "loaded from Postgres into
    NetworkX at process startup" -- and IMPLEMENTATION_STATE.md's "Known
    Issues": wiring this in is Phase 4's job, alongside its first real
    caller). Falls back to a fresh per-request load when the cache isn't
    populated -- startup didn't reach it yet, the catalog wasn't seeded when
    the process started, or (as today) the test suite's `app_client` fixture
    never drives the ASGI lifespan at all. This mirrors the same
    per-request-build tradeoff Phase 2's `SkillNormalizer` already made
    (acceptable at 158-skill / SQLite-in-memory-pool scale).
    """
    cached = getattr(request.app.state, "skill_graph_service", None)
    if cached is not None:
        return cached
    skill_graph = await GraphLoader(CatalogRepository(db_session)).load()
    return SkillGraphService(skill_graph)
