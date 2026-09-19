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

**Design-complete, implementation not started.** See
[`docs/IMPLEMENTATION_STATE.md`](docs/IMPLEMENTATION_STATE.md) for the current
phase and the exact next task.

## Documentation

| Document | Purpose |
|---|---|
| [`docs/EduPath_System_Design.md`](docs/EduPath_System_Design.md) | **Authoritative** system design (v1.0): architecture, agents, data model, API, security, evaluation, phased plan. Read this for "why". |
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

No build yet — see `docs/IMPLEMENTATION_STATE.md` → "Exact Next Task" for the
current entry point (Phase 1: repo skeleton, Docker Compose, FastAPI + Postgres
schema, LLM Gateway, Next.js shell).
