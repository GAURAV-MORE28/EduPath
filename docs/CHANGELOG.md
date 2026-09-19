# EduPath — Changelog

All notable changes to the EduPath project are recorded here, newest first.
This is an engineering changelog (what changed and why it matters for
implementation state), not a marketing changelog.

Format per entry: `## [Phase N | date] Short title` followed by a short bullet list.

---

## [Phase 0 | 2026-09-19] Project initialization + engineering state protocol

- Read `docs/EduPath_System_Design.md` (v1.0, authoritative) in full.
- Created `docs/IMPLEMENTATION_STATE.md` as the canonical handoff file for future
  Claude Code sessions.
- Created `docs/ARCHITECTURE_CONTRACTS.md`, extracting stable contracts (evidence
  tiers, graph conventions, agent I/O schemas, API conventions, DB conventions,
  validator rules, naming conventions, security boundaries) directly from the
  design doc — no new contracts invented.
- Created root `README.md`.
- Initialized git repository; committed Phase 0 state.
- **No application code was written.** No agents, services, API routes, database
  schema, or frontend were implemented this phase, by design.
