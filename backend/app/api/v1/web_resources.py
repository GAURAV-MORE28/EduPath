"""Web-search suggestions for a skill (design §14.3 point 6 / §15.2 "O4").

`GET /api/learners/me/skills/{skill_id}/web-resources` -- extra reading the curated catalog does not
have, found through the Web Fallback Gateway (Tavily when `WEB_SEARCH_PROVIDER=tavily`).

Deliberately *not* wired into planning, the catalog or the Tutor's citations: every result is
`unvetted` (allowlisted https domains only, title-only, never a `resource_id`), it is shown beside --
never merged into -- the curated recommendations, and nothing here can put a URL into a plan. A
degraded provider answers `fetched=false` with a reason; it is never an error.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import get_current_learner_id, get_skill_graph_service
from app.gateway.web_fallback_gateway import WebFallbackQuery, WebFallbackResult, get_web_fallback_gateway
from app.graph.queries import SkillGraphService, UnknownSkillError

router = APIRouter(tags=["web"])


class WebResourcesOut(BaseModel):
    skill_id: str
    label: str
    fetched: bool
    degraded_reason: str | None = None
    results: list[WebFallbackResult] = Field(default_factory=list)
    notice: str = "Unvetted web suggestions: not part of the curated catalog and never added to your plan automatically."


@router.get("/learners/me/skills/{skill_id}/web-resources", response_model=WebResourcesOut)
async def web_resources_route(
    skill_id: str,
    _learner_id: str = Depends(get_current_learner_id),
    graph_service: SkillGraphService = Depends(get_skill_graph_service),
) -> WebResourcesOut:
    try:
        skill = graph_service.get_skill(skill_id)
    except UnknownSkillError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown skill_id") from exc
    response = await get_web_fallback_gateway().search(WebFallbackQuery(skill_label=skill.label, query_text=skill.description or ""))
    return WebResourcesOut(
        skill_id=skill_id, label=skill.label, fetched=response.fetched, degraded_reason=response.degraded_reason, results=response.results
    )
