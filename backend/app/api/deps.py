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

from fastapi import Cookie, HTTPException, status

from app.config import get_settings


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
            return "dev-user"
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return session
