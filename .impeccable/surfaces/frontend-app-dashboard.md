---
version: 1
slug: "frontend-app-dashboard"
primary_target: "frontend/app/dashboard"
related_targets: ["frontend/app/page.tsx","frontend/app/start"]
---

# Surface brief: EduPath learner app (/dashboard/*, /start, and the / entry)

Scope and mode: Operate for the authenticated app (overview, evidence, skill map, gaps, plan, practice, progress, tutor, trace). The entry page and onboarding are Persuade-then-Operate but inherit the same world; they are not a second identity.

Audience and job: a career-switching student or early-career learner on a laptop or phone, at a desk in the evening, trying to know where they stand, what to do this week, and why the plan changed. A mentor or judge may read over their shoulder and must find the evidence and reasoning in seconds.

Task and proof: real backend data only (roles, gaps, plans, evidence spans, revisions, decisions, live SSE trace). Demo learner only when NEXT_PUBLIC_DEMO_MODE=true, uploaded through the real APIs.

Chosen direction: The Checked Set (drawing-set world), assigned by the roll and confirmed by the user. Memorable moment: a failed assessment draws a clouded revision on the plan, Rev A to Rev B, with the reason and citations in the revision block.

Unresolved decisions: none blocking. Light only (a set viewed on a lit desk); no dark theme.

## Direction contract

THESIS: Your career path issued as a checked drawing set. Every claim is a cited drawing note, every status is line form, every change to the plan is a dated, clouded revision with its reason. Refuses the category default of a sidebar with stat cards and progress rings.

OWN-WORLD: Cool drafting-film ground (#F1F3F2) with lighter plate sheets (#FAFBFA) laid on it, graphite ink (#16202A) linework at 1px, viridian (#0E7A63) only for verified and mastered, revision red (#C42D17) only for change and struggle. Radius 0-2px, hairline rules, an 8px module grid, title-block registers with ruled cells, revision triangles and scalloped revision clouds. State is drawn as line form (solid, half-filled, dotted, dashed, struck), never hue alone. One humane sans (Atkinson Hyperlegible Next) for all text with tabular numerals; a condensed drafting face only for title-block numbers.

STORY: The learner sees, within a viewport, where they stand, where they are going, what is missing, what to do now, and why. They believe the system because each claim carries its source span and tier. They act by starting the one next item named in the title block.

FIRST VIEWPORT: Overview sheet. A ruled title block strip across the top (role, week, revision, evidence count) ending in a single next-action cell with the primary button. Below it, left two thirds: this week's plan as a ruled register (skill, task, minutes, status) beside a compact skill map thumbnail; right third: gap register and any struggle signal, plus a "why this plan" note citing evidence. The adaptive loop ribbon runs along the bottom edge of the title block, lit to the current stage.

FORM: Architectural drawing set with revision management, candidate 3 of the ordered list (1 transit diagram, 2 scholarly apparatus, 3 drawing set, 4 specimen plate, 5 chess annotation, 6 survey chart, 7 lab notebook); seed key e3b9ec5d. Raised by state-as-line-form (emission-line rail), a single measured grid (oscilloscope graticule), one imperative per sheet (WPA poster).

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance.
