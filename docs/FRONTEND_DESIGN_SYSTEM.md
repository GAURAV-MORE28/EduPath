# EduPath — Frontend Design System ("The Checked Set")

> Source of truth for how the EduPath UI looks and behaves. Product truth lives in
> `PRODUCT.md`; the direction contract in `.impeccable/surfaces/frontend-app-dashboard.md`;
> tokens are implemented in `frontend/app/globals.css`. If code and this file disagree,
> fix whichever is wrong in the same change.

## 1. Where these rules came from

- **Impeccable** chose the visual world. The direction round dealt "The Checked Set" (seed
  `e3b9ec5d`): a career path issued as an architectural drawing set. The user confirmed it.
  Challengers folded in as named raises: state as line form (Emission-Line Rail), one measured
  grid (Oscilloscope Bench), one imperative per sheet (WPA Poster).
- **UI/UX Pro Max** (installed to `.claude/skills/ui-ux-pro-max`) supplied the UX and
  accessibility rules used below (contrast 4.5:1, 44px touch targets, visible focus,
  reduced motion, 150–300ms micro-interactions, skeletons over spinners, no emoji icons,
  responsive at 375/768/1024/1440). Its generated palette and font pairing for
  "education" (playful indigo, Baloo 2/Comic Neue) were **rejected**: they contradict the
  brief (calm, premium, not a developer tool, no purple).
- **Anthropic frontend-design** guidance: commit to one point of view, spend boldness in one
  place, keep everything else quiet.
- **21st**: the MCP is configured and reports connected, but its tools are not loaded into a
  session until restart, so no 21st component was used. Component decisions were made from
  the shadcn/ui registry and first principles.

## 2. Brand direction and personality

EduPath is a **personal learning intelligence system**. It should feel like a well-kept
drawing set: precise, checked, dated, reversible. Intelligent because it shows its working;
premium because of restraint and craft; trustworthy because every claim is cited and every
change carries its reason; calm because there is one next action per sheet.

Refused: purple gradients, glass, glowing borders, 3D, gradient text, hero-metric cards,
icon-tile card grids, ALL CAPS eyebrows, colored side-borders, dashboard "stat card" rows.

## 3. Color system

Light only (a set is read on a lit desk). Restrained strategy: neutrals plus two meaning colors.

| Token | Hex | Role | Contrast |
|---|---|---|---|
| `--sheet` | `#F1F3F2` | page ground (drafting film) | — |
| `--paper` | `#FAFBFA` | plates laid on the film | — |
| `--plate` | `#E7EBEA` | second neutral: rail, wells | — |
| `--ink` | `#16202A` | text, linework, primary action | 14.8:1 on sheet |
| `--ink-2` | `#414C56` | secondary text | 7.9:1 |
| `--ink-3` | `#4F5B65` | tertiary text | ≥5.4:1 on sheet, ≥4.5:1 on plate |
| `--rule` | `#CBD2D5` | decorative hairlines | — |
| `--rule-strong` | `#7C878E` | meaningful edges | 3:1 |
| `--verified` | `#0D7561` | verified / mastered / done only | 5.1:1 on paper |
| `--revision` | `#C42D17` | change, struggle, undo only | 5.4:1 on paper |
| `--verified-wash`, `--revision-wash` | `#E6F3EF`, `#FBE9E5` | tinted grounds | — |

Rules: color never carries status alone (see §11). Viridian means *proven*; revision red
means *changed or struggling*; nothing else may use them. Blocked, missing and weak use ink.

## 4. Typography

- **Atkinson Hyperlegible Next** for everything (one family, chosen for legibility and because a
  learning tool should be readable by everyone). Tabular numerals on by default.
- **Barlow Semi Condensed** (500/600) only for title-block registers and numerals: drafting
  lettering, class `.draft`. Never for buttons or labels.
- Fixed rem scale, ratio ≈1.2 (product UI does not use fluid type): 13 / 14 / 16 / 19 / 23 /
  28 / 34 / 44 / 60 px. Body 16px on 1.55 line height; prose measure ≤ 68ch.
- Headings: weight 700, tracking −0.015em (−0.03em for the landing display), balanced wrapping.
- No monospace anywhere; IDs and spans are set in the text face.

## 5. Spacing, radius, shadow

- **8px module** (`--module`). Component padding 12/16/20/24; section gaps 24–32.
- **Radius 0–2px.** Plates are square; controls 2px. The one exception is radio glyphs (circles).
- **Depth:** hairline borders (`.plate` 1px strong, `.plate-quiet` 1px light). No decorative
  shadows. The single lift shadow (`--shadow-lift`) is reserved for overlays.
- Overlays (`Sheet` drawers) dim the page with ink at 25%, no blur.

## 6. Component principles

- One vocabulary: the same button, plate, register and drawer everywhere.
- Plates are never nested inside plates. Repeated rows are **registers** (`.reg`, ruled rows),
  not cards.
- Every interactive component has default, hover, focus (2px ink outline, 2px offset), active,
  disabled and loading (`aria-busy`) states.
- Domain components live in `frontend/components/edupath/`; shadcn primitives in
  `components/ui/` (base-nova / Base UI), restyled to the tokens.

| Component | Purpose |
|---|---|
| `SkillGlyph`, `SkillStatus`, `SkillChip`, `StateLegend` | the six skill states as line form |
| `TierBadge`, `CitationBadge`, `EvidenceCard` | evidence with source, span and tier (E0–E3) |
| `SkillGraph`, `SkillDrawer` | layered prerequisite network; per-skill detail |
| `GapCard`, `LevelGauge`, `ObjectiveCard`, `ResourceCard` | gaps, objectives, real catalog resources |
| `WeeklyPlan`, `PlanItemRow`, `BudgetBar`, `RevisionMark` | the plan register |
| `AdaptiveMoment`, `RevisionCloud`, `RevisionHistory` | the centrepiece (§8) |
| `WhyDrawer` | evidence, graph path and decision record behind any decision |
| `PracticeCard`, `AssessmentResult`, `StruggleSignalCard` | assess and struggle |
| `TutorMessage` | a turn with its checked citations |
| `AgentTrace` | live SSE trace |
| `LoopRibbon`, `StateBar`, `SheetHeader`, `NextAction` | orientation |
| `EmptyState`, `LoadingState`, `ErrorState`, `DegradedNotice` | non-happy paths |

## 7. Interaction principles

- One imperative per sheet: the title block ends in a single next-action strip.
- Every claim has a way to ask "why": Why drawer, evidence card, decision record.
- Destructive or plan-changing actions are reversible or confirmed inline (revert is a two-step
  inline confirm, never a modal).
- Mutations show pending state on the control and reconcile from the server (no fake success).
- Modals are avoided; drawers are used only for detail that should not lose the page.

## 8. Animation principles (Motion for React, `import { motion } from "motion/react"`)

- Motion answers an action or shows a state change. No scroll-triggered fade-ups, no hover
  choreography. Durations 150–350ms; `[0.16,1,0.3,1]` ease-out; springs for layout.
- **One authored moment:** the revision cloud. In `AdaptiveMoment` the six-step causal chain
  lights in sequence, the AFTER list opens, inserted work slides in with a spring layout
  animation and a scalloped cloud is drawn stroke by stroke (`pathLength`), each marked with
  a revision triangle. Replay is user-triggered.
- Smaller purposeful motion: state-bar segment widths, done-tick spring, budget bar fill,
  trace events entering, skill-node fill on state change.
- `MotionConfig reducedMotion="user"` at the root plus explicit `useReducedMotion` in the
  moment: reduced motion shows the finished state with no playback. CSS animation/transition
  durations are clamped under `prefers-reduced-motion`.
- The skill graph is lazy-loaded (`next/dynamic`).

## 9. Accessibility rules

WCAG 2.2 AA. Skip link first tab stop; landmarks (`header`, `nav`, `main`); one `h1` per sheet
(inside `SheetHeader`); native radios/checkboxes for choices; `role="checkbox"` only where a
custom control is required; labels on every input; icon-only controls named; decorative SVG
`aria-hidden`; graph nodes are real buttons with `aria-pressed` and a text state; status is
glyph + word; live regions for loading/trace/progress; 44px touch targets below `md`.
Verified by `frontend/e2e/smoke.spec.ts` (axe wcag2a/2aa/22aa, serious+critical, all routes).

## 10. Dashboard principles

The Overview answers, in order of weight: **Do this next** (largest), **Where you stand**,
**What's missing**, **Anything wrong?**, **Why this plan**, **Are you improving?**. Where you
are going is in the title block (role) and the state sentence. The adaptive loop ribbon shows
the stage the learner is in, lit from real data (`lib/derived.ts::loopStages`).

## 11. Skill states as line form

| State | Glyph | Meaning |
|---|---|---|
| mastered | double ring, filled, tick (viridian) | evidence meets the role's level |
| developing | ring, lower half filled | some evidence, below level (WEAK with level ≥ 1) |
| weak | ring with bar | evidence below foundational (WEAK, level 0) |
| unverified | dotted ring | claimed, unproven: probe first |
| missing | long-dash ring | no evidence |
| blocked | struck square | a hard prerequisite is weak/missing |

Evidence tier E0–E3 is drawn as 1–4 stacked rules plus the tier code and its name.

## 12. Mobile and responsive rules

Breakpoints: 375 (phone), 768, 1024 (rail appears), 1440. Below 1024: sticky top bar, bottom
tab bar (Overview, Plan, Skill map, Tutor, More → drawer). The skill map becomes a staged list
below 768. Tables scroll inside their own container. Title-block registers reflow to a 2×2 grid.
No horizontal page scroll at any width (tested).

## 13. Data visualization rules

Only encode what is true: state bar (counts by state, line-form fills), level gauge (three
steps, tick at required level), budget bar (planned vs weekly hours), mastery bar with level
thresholds ticked. No sparklines, rings or gradients as decoration. Every chart has a text
equivalent (`aria-label` or adjacent numbers).

## 14. Empty, loading, error, degraded states

- **Empty** teaches and offers the one action that fills it (`EmptyState`): no plan, no
  evidence, no resources ("EduPath will not invent a link"), no objectives, nothing to practise,
  unsupported role.
- **Loading**: skeleton plates that hold layout (`LoadingState` register/plate/grid), never a
  centred spinner.
- **Error** (`ErrorState`): says what failed and how to recover, with retry. Distinguishes API
  unreachable, 404, "role not supported", 5xx and rejected requests.
- **Degraded** (`DegradedNotice`): "Running without a language model." Shown wherever a
  response carries `degraded`/`conservative`.

## 15. AI-specific interaction patterns

- Evidence before assertion: skill → quoted span → source → tier.
- Estimates carry confidence and band; never a bare number as fact.
- The Tutor cites checked records; conservative answers say they had no model wording.
- Struggle is named with the classifier's confidence; duplicates collapse to the strongest.
- Model unavailability is a first-class state, not an error.
- Demo data appears only under `NEXT_PUBLIC_DEMO_MODE=true` and goes through real endpoints.

## 16. Agent trace visualization principles

A vertical rule is the run. Each event: agent name, kind label (Input, Graph, Decision, Check,
Reflection, Re-plan, Fallback, Error), summary, offset in seconds. The top event pulses while
running. Events come only from the backend's SSE stream (`X-Run-Id` → `/api/runs/{id}/events`,
with replay). If the stream fails to open the panel says so instead of inventing events.
