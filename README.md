# EduPath

EduPath is an adaptive learner-intelligence system, not a chatbot that recommends
courses. Its core is a closed loop:

```
Evidence → Skill Understanding → Gap Diagnosis → Personalized Planning → Learning
→ Assessment → Struggle Detection → Reflection → Re-planning → Memory Update → (repeat)
```

A learner provides a target role, weekly hours and preferences, and uploads a
resume, project descriptions, certificates or a GitHub link. EduPath extracts
evidence-backed skills, diffs them against a curated skill graph for the target
role, generates a personalized weekly plan, produces practice whose wrong answers
are pre-tagged with catalogued misconceptions, detects genuine struggle (not just
low scores), and explains and revises the plan — visibly and undoably — as new
evidence arrives.

## Status

**Implemented end to end and hardened (Phase 12).** All five agents, every deterministic service, the
premium frontend, persisted observability, record/replay, a seeded demo mode, and automated
integration / evaluation / security suites. See
[`docs/FINAL_IMPLEMENTATION_STATUS.md`](docs/FINAL_IMPLEMENTATION_STATUS.md) for what works, the
measured evaluation numbers, known limitations, demo instructions and deployment commands.

## Documentation

| Document | Purpose |
|---|---|
| [`docs/EduPath_System_Design.md`](docs/EduPath_System_Design.md) | **Authoritative** system design (v1.0): architecture, agents, data model, API, security, evaluation, phased plan. Read this for "why". |
| [`docs/FINAL_IMPLEMENTATION_STATUS.md`](docs/FINAL_IMPLEMENTATION_STATUS.md) | **Start here for a demo or a review:** completed features, remaining bugs, known limitations, demo instructions, environment variables, test commands, deployment. |
| [`docs/IMPLEMENTATION_STATE.md`](docs/IMPLEMENTATION_STATE.md) | Canonical handoff file — current phase, completed work, known issues, exact next task. Read this first when resuming work. |
| [`docs/ARCHITECTURE_CONTRACTS.md`](docs/ARCHITECTURE_CONTRACTS.md) | Stable contracts (agent I/O schemas, evidence tiers, graph/DB/API conventions, validator rules) extracted from the design doc. |
| [`docs/CHANGELOG.md`](docs/CHANGELOG.md) | Engineering changelog, newest first. |
| [`research_papers/`](research_papers/) | Background research papers (reference only; not re-read for the design doc — see its header note). |

## Architecture at a glance

Modular monolith: FastAPI (Python 3.11+) + Next.js + PostgreSQL (with pgvector and
FTS), orchestrated with LangGraph. Five LLM agents (Profiler, Planner, Assessor,
Reflection, Tutor); everything else — gap analysis, mastery updates, struggle
classification, plan validation, ranking, reporting — is deterministic code. Full
rationale in `docs/EduPath_System_Design.md` §5–8 and §41.

## Getting started

```bash
cp .env.example .env            # defaults work: no LLM key needed (deterministic "reduced-intelligence" mode)
docker compose up --build       # postgres + api (migrates, seeds the catalog) + web
# web: http://localhost:3000    api: http://localhost:8000/api/health
```

Demo (seeded persona + scripted struggle, works offline): set `DEMO_MODE=true` in `.env`, rebuild
(`docker compose up --build`), then `docker compose exec api python scripts/seed_demo.py` and open the
app. Smoke test / benchmark of the whole journey against the running stack:
`docker compose exec api python scripts/run_journey.py --iterations 3 --demo-seed`.

Tests: `cd backend && python -m pytest -q` (unit, integration, evaluation, security). Full
instructions: [`docs/FINAL_IMPLEMENTATION_STATUS.md`](docs/FINAL_IMPLEMENTATION_STATUS.md).
