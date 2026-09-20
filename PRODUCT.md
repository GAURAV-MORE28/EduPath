# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary: a career-switching student or early-career learner (persona: "Asha", third-year AI/ML undergraduate, 5 hours a week, targeting ML Engineer, one independent object-detection project). They want a credible path to a target role and they want to understand *why* the system believes what it does about their skills, so they can trust it or dispute it.

Secondary reader (not a separate persona): a mentor or hackathon judge who scans the same screens and needs the evidence and reasoning legible at a glance.

## Product Purpose

EduPath is an AI-powered adaptive career-learning system. It turns a learner's resume, self-report and GitHub work into an evidence-graded picture of their skills, diagnoses the gap to a target role, builds a weekly plan from a curated skill graph and real resources, assesses them, and when they struggle it finds the root cause and re-plans. Success is a learner who knows where they stand, what to do this week, and why the plan changed when it did.

## Positioning

Every skill claim is tied to a verbatim span in a source document and an evidence tier (E0 self-reported, E1 documented, E2 artifact-verifiable, E3 assessed in-system); only evidence can satisfy a role requirement. Gap analysis, validation and mastery are deterministic code; LLMs propose and narrate but never decide. When a learner fails an assessment the system traces a misconception to a prerequisite, revises the plan through a closed set of operators, and shows the diff with citations. A generic course recommender cannot truthfully show that chain.

## Operating Context

- Learner flow: intake (target role, weekly hours, preferences) → resume/GitHub upload → review and confirm extracted claims → gap report → weekly plan → practice (MCQ item sets) → submit → mastery update, struggle signals, possible reflection and plan revision (with one-click revert) → progress report → grounded tutor chat.
- Backend: FastAPI under `/api`, session cookie identity (dev fallback user in `env=dev`), REST plus SSE for run traces (`GET /api/runs/{run_id}/events`). Curated graph `v0.1.0-domain-pack`: 158 skills, 3 roles, 140 resources, 18 misconceptions, 95 items.
- The backend currently runs with `LLM_PROVIDER=none`: every agent resolves through its deterministic fallback, and responses carry `degraded` flags the UI must surface honestly.
- Learners and reviewers will see the product on laptops and phones.

## Capabilities and Constraints

- Real backend APIs only. No hard-coded production data. Demo data appears only when demo mode is explicitly enabled (`NEXT_PUBLIC_DEMO_MODE=true`); the confirmed demo path uploads the demo resume (`data/dataset/demo/demo_resume.md`) and submits Asha's intake through the real endpoints, so all gaps, plans and reflections are still computed by the system.
- Supported roles are only those in the curated graph; an unsupported role must say so, never be invented.
- The practice API never returns answer keys or misconception tags; the UI cannot show them before grading.
- Mastery is an estimate with a band and confidence, never a bare number asserted as fact. Numeric thresholds are tunable engineering defaults, not derived constants.
- The Tutor is read-only and cites evidence; it cannot change the plan.
- The backend emits no trace events onto the SSE bus yet; a trace UI must consume real events when they exist and must not fabricate them.
- Stack is the existing Next.js 16 App Router, React 19, Tailwind v4, shadcn/ui (base-nova), Motion for React.

## Brand Commitments

Name: EduPath. The product should read as a personal learning intelligence system: intelligent, focused, trustworthy, calm, technical without reading as a developer tool. Explicit avoid list from the owner: excessive purple gradients, glass everywhere, glowing borders, unnecessary 3D, excessive animation, visual noise.

## Evidence on Hand

Real content only: the curated domain pack in `data/dataset/`, the demo persona files in `data/dataset/demo/`, and whatever the live API returns. There are no customer testimonials, benchmarks, user counts or pricing; none may be invented.

## Product Principles

1. Evidence before assertion: a skill status is never shown without its source, span and tier.
2. Show the reasoning: every plan item and every change to the plan carries a "why" a learner can open.
3. The adaptive loop is the product: evidence → understanding → gap → plan → learn → assess → struggle → reflect → re-plan → progress must be visible as one continuous story.
4. Be honest about uncertainty and degradation: estimates carry confidence, degraded runs say so, empty and failed states explain what to do.
5. Calm by default: the learner's next action is always obvious and nothing competes with it.

## Accessibility & Inclusion

Target WCAG 2.2 AA: keyboard operable, visible focus, 4.5:1 text contrast, screen-reader labels on all icon-only controls and graph nodes, `prefers-reduced-motion` honored for every animation. Status is never conveyed by color alone.
