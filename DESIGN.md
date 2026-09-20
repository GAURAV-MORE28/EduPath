---
name: EduPath
description: A career path issued as a checked drawing set, with cited claims and dated, clouded revisions.
colors:
  sheet: "#f1f3f2"
  paper: "#fafbfa"
  plate: "#e7ebea"
  ink: "#16202a"
  ink-2: "#414c56"
  ink-3: "#4f5b65"
  rule: "#cbd2d5"
  rule-strong: "#7c878e"
  verified: "#0d7561"
  verified-wash: "#e6f3ef"
  revision: "#c42d17"
  revision-wash: "#fbe9e5"
typography:
  display:
    fontFamily: "Atkinson Hyperlegible Next, ui-sans-serif, system-ui, sans-serif"
    fontSize: "4rem"
    fontWeight: 700
    lineHeight: 1.05
    letterSpacing: "-0.03em"
  headline:
    fontFamily: "Atkinson Hyperlegible Next, ui-sans-serif, system-ui, sans-serif"
    fontSize: "2.125rem"
    fontWeight: 700
    lineHeight: 1.15
    letterSpacing: "-0.015em"
  title:
    fontFamily: "Atkinson Hyperlegible Next, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.1875rem"
    fontWeight: 700
    lineHeight: 1.15
    letterSpacing: "-0.015em"
  body:
    fontFamily: "Atkinson Hyperlegible Next, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: "normal"
  label:
    fontFamily: "Atkinson Hyperlegible Next, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "normal"
  draft:
    fontFamily: "Barlow Semi Condensed, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "0.01em"
rounded:
  sm: "1px"
  md: "2px"
  xl: "3px"
spacing:
  module: "8px"
  measure: "68ch"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    rounded: "{rounded.md}"
    typography: "{typography.label}"
    padding: "0 16px"
    height: "40px"
  button-primary-hover:
    backgroundColor: "{colors.ink-2}"
  button-outline:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "40px"
  button-outline-hover:
    backgroundColor: "{colors.plate}"
  button-verified:
    backgroundColor: "{colors.verified}"
    textColor: "{colors.paper}"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "40px"
  button-revision:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.revision}"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "40px"
  button-revision-hover:
    backgroundColor: "{colors.revision-wash}"
  plate:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
  skill-chip:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    padding: "4px 8px"
  index-rail:
    backgroundColor: "{colors.plate}"
    textColor: "{colors.ink}"
    width: "248px"
---

# Design System: EduPath

## Overview

**Creative North Star: "The Checked Set"**

A learner's career path issued as an architectural drawing set. A cool drafting-film ground carries lighter paper plates framed in hairlines; every claim is a cited drawing note and every change to the plan is a dated revision with its reason. It is a light-only world (a set is read on a lit desk); there is no dark theme.

Density is calm and ruled: title-block registers with divided cells, not stat cards or progress rings. Status is drawn as line form (solid, half-filled, dotted, dashed, struck) so meaning never rests on hue alone. Two hues carry meaning and nothing else: viridian for verified, revision red for change and struggle.

**Key Characteristics:**
- Film ground, paper plates, 1px graphite linework, radius 1-3px.
- One humane sans for all text, with tabular numerals everywhere; a condensed drafting face only for title-block numbers and sheet marks.
- State as line form via the six-glyph skill vocabulary, always paired with its word.
- Depth is tonal and drawn, not shadowed.
- One authored motion: the revision cloud drawn stroke by stroke.

## Colors

Cool grey-green film and graphite ink, with exactly two signal hues held in reserve.

### Primary
- **Graphite Ink** (`ink`): text, primary button, focus ring, selection, and the active-nav top rule. The system's default "action" color; there is no brand accent.

### Secondary
- **Viridian Check** (`verified`, wash `verified-wash`): only for verified and mastered states, the verified button, and healthy-system dots.
- **Revision Red** (`revision`, wash `revision-wash`): only for change and struggle: revision marks and clouds, the current loop stage, the revision button, destructive actions, and the input caret.

### Neutral
- **Drafting Film** (`sheet`): page ground.
- **Plate Paper** (`paper`): plates, cards, popovers, inputs.
- **Index Plate** (`plate`): second neutral layer for the index rail, wells, secondary and hover fills.
- **Ink 2 / Ink 3** (`ink-2`, `ink-3`): secondary and tertiary text; both are tuned to hold text contrast on sheet and paper.
- **Hairline** (`rule`): decorative dividers and register rows.
- **Strong Hairline** (`rule-strong`): meaningful edges (plate frames, input borders, dashed and struck lines), sized for 3:1 on the sheet.

### Named Rules
**The Two Signals Rule.** Viridian means verified, red means change. Neither is used for decoration, emphasis, or a generic success/error pair.
**The Line-Form Rule.** A state is never conveyed by hue alone; it is a glyph shape plus a word.

## Typography

**Display / Body Font:** Atkinson Hyperlegible Next (with ui-sans-serif, system-ui)
**Draft Font:** Barlow Semi Condensed (with ui-sans-serif, system-ui)

**Character:** a legible, humane sans set with tabular numerals (`tnum`), against a narrow drafting face that reads as title-block lettering.

### Hierarchy
- **Display** (700, 2.5rem/3.5rem/4rem responsive on the entry page, 1.05, -0.03em): landing headline only.
- **Headline** (700, 1.75rem mobile / 2.125rem, 1.15): the sheet title in each title block.
- **Title** (700, 1.1875rem down to 0.9375rem, 1.15-1.3): plate headings and item titles.
- **Body** (400, 1rem, 1.55; secondary copy 0.9375rem): reading text, capped at 68ch (`measure`).
- **Label** (600, 0.8125rem, sentence case): status words, chips, register keys. A 0.75rem sentence-case caption is used for cell keys.
- **Draft** (600, 1.25rem, tabular): week, revision letter, sheet numbers, revision-triangle letters only.

The product scale is fixed rem, ratio about 1.2, no fluid type in app surfaces (steps 0.8125, 0.875, 1, 1.1875, 1.4375, 1.75, 2.125, 2.75, 3.75rem).

### Named Rules
**The Draft-Face-Is-Data Rule.** The condensed face carries numbers and marks, never UI labels or prose.

## Layout

A single 8px module grid and a 75rem content column. At `lg` the app is a 15.5rem index rail (`plate` ground, strong hairline edge) beside the content; below `lg` the rail becomes a sticky top bar with a five-tab bottom bar and a "More sheets" bottom drawer. Each sheet opens with a title block: title and purpose on the left, a two-column register (role, week, revision, hours) on the right, and an optional next-action strip. Registers are ruled lists (`reg`: hairline between rows). One imperative per sheet. Touch targets are 44px on small screens, 32-40px on desktop.

## Elevation & Depth

Flat and tonal. Depth is a paper plate on film, a strong 1px hairline, and the index plate as a second neutral. Selection is drawn with an inset 2px ink top rule (nav) or a 2px ink outline ring (skill node), not a shadow. The build defines a `shadow-lift` token that no component consumes; overlays (the bottom sheet) use a stock `shadow-lg`.

### Named Rules
**The Drawn-Depth Rule.** Layers are separated by ground tone and hairline, not by blur.

## Shapes

Square, drafted. Radius is 1px on focus, 2px on buttons and plates, 3px at most. Frames are 1px; `rule-strong` for edges that carry meaning and `rule` for decoration. Recurring forms: revision triangle with a draft-face letter, scalloped revision cloud, dashed/dotted rings, and a strikethrough (`struck`, 1px in `rule-strong`) for blocked skills and removed plan items.

## Components

### Buttons
- **Shape:** 2px corners, 1px transparent or hairline border, semibold 0.875rem.
- **Primary:** graphite fill, paper text, `min-h` 44px mobile / 40px desktop, 16px side padding; hover shifts to `ink-2`.
- **Outline / Secondary / Ghost:** paper with strong hairline; plate fill; text-only. Hover goes to `plate`.
- **Verified:** viridian fill for confirming a verified state. **Revision:** paper with red border and text, for changing or undoing the plan only; hover is `revision-wash`.
- **Focus:** 2px ink outline, 2px offset. Disabled at 45% opacity. Color transitions 150ms.

### Plates and registers
Paper on film with a 1px strong (`plate`) or light (`plate-quiet`) hairline; rows separate by hairline. Padding steps on the 8px module (16-20px).

### Skill glyph, status, chip, legend
Six 20px SVG line forms (mastered double-ring filled with tick, developing half-filled, weak bar, unverified dotted, missing dashed, blocked struck square) paired with their word. Chips are paper with a strong hairline.

### Navigation
Index rail on plate ground; the active entry is paper, bold, with an inset 2px ink rule at the top. Lucide outline icons at 18px sit beside each label. Mobile is a five-tab bottom bar.

### Loop ribbon
The adaptive loop as one line of 20px square nodes: done is filled ink with tick, current is a red-outlined node with a red center square, todo is empty with a dashed connector.

### Revision mark and cloud (signature)
A red triangle carrying the draft-face revision letter marks added items; a scalloped red cloud (1.5px stroke) is drawn around changed content over 0.9s with an expo-out ease. Reduced-motion collapses it to instant.

## Do's and Don'ts

### Do:
- **Do** use `ink` for every default action and `verified` / `revision` only for their meanings.
- **Do** pair every state glyph with its word and a distinct line form.
- **Do** build on the 8px module, 2px radius, 1px hairlines, tabular numerals.
- **Do** honor `prefers-reduced-motion`; the revision cloud is the one authored motion.
- **Do** keep sheet titles in a title block with one next action.

### Don't:
- **Don't** add a dark theme, gradients, glass, or blurred shadows.
- **Don't** use stat-card grids, progress rings, or a hue-only status dot.
- **Don't** use the draft face for labels or prose.
- **Don't** round beyond 3px or add pill shapes.
- **Don't** use red or viridian as decoration or as generic error/success.
- **Don't** consume the unused `shadow-lift` token as a house style, or replicate the overlay's stock `shadow-lg`; both are carried drift, not system.
