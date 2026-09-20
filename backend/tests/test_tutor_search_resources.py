"""Regression (Phase 12): the Tutor's `search_resources` must give the retrieval service the same
`met_skill_ids` the Planner does. Without it every resource that has a prerequisite was "ineligible" and the
Tutor answered "0 catalog resource(s) found" for skills that do have resources."""
from __future__ import annotations

import pytest

from app.tutor.tools import search_resources

pytestmark = pytest.mark.asyncio


async def test_search_resources_passes_the_learners_met_skills_to_retrieval(catalog_session):
    from app.db.models import LearnerProfile, User
    from app.graph.loader import GraphLoader
    from app.graph.queries import SkillGraphService
    from app.repositories.catalog_repository import CatalogRepository
    from app.tutor.service import build_tutor_context

    catalog_session.add(User(user_id="sr-user", email_hash="sr-user"))
    await catalog_session.flush()
    catalog_session.add(
        LearnerProfile(learner_id="sr-learner", user_id="sr-user", target_role_id="role.ml_engineer", career_goal="", experience_summary="", weekly_hours=6, preferences={}, constraints={})
    )
    await catalog_session.commit()
    graph = SkillGraphService(await GraphLoader(CatalogRepository(catalog_session)).load())
    ctx = await build_tutor_context(catalog_session, graph, "sr-learner")

    captured: dict = {}
    real = ctx.retrieval_service.recommend_for_skill

    async def spy(**kwargs):
        captured.update(kwargs)
        return await real(**kwargs)

    ctx.retrieval_service.recommend_for_skill = spy
    result = await search_resources(ctx, skill_id="skill.python")
    assert result.error is None
    assert "met_skill_ids" in captured, "the Tutor must pass the learner's MET skills, like the Planner does"
    assert captured["met_skill_ids"] == {g.skill_id for g in ctx.gap_result.gaps if g.status == "MET"}
