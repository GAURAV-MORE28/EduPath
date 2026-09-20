"""API v1 aggregate router.

Design §27: endpoint surface is namespaced under `/api/...`. This module is
the single place later phases register their routers, so versioning stays
centralized (`/api/v1/...` mounted under the `v1` prefix from `main.py`, with
`/api/...` aliases where the design doc's endpoint table omits a version
segment).
"""
from fastapi import APIRouter

from app.api.v1.gap import router as gap_router
from app.api.v1.health import router as health_router
from app.api.v1.learners import router as learners_router
from app.api.v1.plans import router as plans_router
from app.api.v1.practice import router as practice_router
from app.api.v1.runs import router as runs_router
from app.api.v1.tutor import router as tutor_router
from app.api.v1.views import router as views_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(runs_router)
api_router.include_router(learners_router)
api_router.include_router(gap_router)
api_router.include_router(plans_router)
api_router.include_router(practice_router)
api_router.include_router(tutor_router)
api_router.include_router(views_router)
