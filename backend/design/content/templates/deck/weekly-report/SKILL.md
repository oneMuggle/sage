---
name: weekly-report
kind: deck
description: "Weekly/monthly report deck: data cards with KPIs, progress bars, task completion summaries, and action items. Clean, scannable, professional."
design_system_required: true
---

# Weekly Report Template

Generate a self-contained HTML deck for recurring team reports: weekly
updates, project status meetings, sprint reviews, and monthly summaries.

## Intent

- **Audience:** team members, stakeholders, and managers who need the status
  in **five minutes or less**.
- **Goal:** answer three questions fast — *what moved, what is stuck, what
  happens next.*
- **Tone:** factual, scannable, professional. No storytelling, no marketing
  language, no filler.
- **Read order:** Cover -> Executive Summary -> KPIs -> Progress -> Tasks ->
  Timeline -> Risks -> Next Period. Skip layouts that have no data rather
  than padding them.

Every slide should be understandable at a glance. If a slide requires a
paragraph of explanation, it is the wrong layout.

## Typography

- **Family:** `Inter` first, falling back to the system sans stack
  (`-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`).
  No serif, no display faces, no decorative fonts.
- **KPI numbers:** large — `2.5rem` minimum, up to `3rem` for a hero metric.
  Weight 700, `font-variant-numeric: tabular-nums`.
- **Body text:** `1rem`, line-height 1.5. Descriptions are one line; if they
  need two, shorten them.
- **Labels:** `0.75rem`, `text-transform: uppercase`, `letter-spacing: 0.05em`,
  muted colour. Used for metric labels, column headers, and section eyebrows.
- **Slide titles:** `1.75rem`–`2rem`, weight 600.
- Numbers must align vertically across a row — always use `tabular-nums`.

## Layout Types

### L01 — Cover

Report title, reporting period (e.g. `Q4 2026 · Week 12`), team or
department name, and the presentation date. One screen, nothing else. No
agenda, no logo grid, no decorative background art.

### L02 — Executive Summary

Three to four key highlights in **large text**, one per line. Each line is a
single outcome with a leading verb (`Shipped`, `Blocked`, `Hired`). Include
no more than one supporting number per line. This slide must be readable in
under 15 seconds.

### L03 — KPI Dashboard

A 2x2 or 3x2 grid of metric cards. Each card contains:

- **Label** — small uppercase, muted
- **Big number** — 2.5–3rem, tabular-nums, right-aligned
- **Delta** — arrow up/down plus value and comparison basis
  (`+12% vs last week`, `-3d vs target`)
- **Sparkline** — small inline SVG area chart of the last 4–8 periods,
  drawn in the accent colour at low opacity. Optional, but if omitted the
  delta must still carry a comparison.

### L04 — Progress Bars

A list of initiatives (max 8). Each row shows the initiative name, a
horizontal bar, and the percentage. The bar is a subtle track with an
accent-colour fill whose width equals the completion percentage. Label and
percentage sit above or beside the bar; the percentage is right-aligned and
tabular. Colour the fill by status only if status is meaningful — otherwise
keep the fill in one accent colour.

### L05 — Task Summary

Three columns — **Done**, **In Progress**, **Blocked** — each with a count
in the header and the key items listed beneath (max 8 items per column, 3–5
is better). Blocked items must state what they are blocked on. No checkboxes,
no assignee avatars; the count and the item text carry the message.

### L06 — Timeline

A horizontal timeline of the key events or milestones in the reporting
period. Each marker has a date, a short label, and at most one line of
detail. Keep it to 5–7 markers; if there are more, group them.

### L07 — Risk / Issue

Risk items, one per row. Each row has:

- A **severity dot**: red = critical, yellow = caution, green = resolved /
  monitor
- The risk statement (one line)
- Mitigation status or owner (`Mitigation: vendor SLA renegotiation — on
  track`)

Only colour the dot — never colour the whole row. Max 8 risks.

### L08 — Next Period

Three to five action items. Each item has a description, an **owner**, and a
**deadline**. Format each row as `.action` with `.owner` and `.due` aligned
right. Deadlines use an absolute date (`Nov 18`), never "next week".

## Data Styling

- **Numbers** are right-aligned in tabular columns and use
  `font-variant-numeric: tabular-nums`. Never centre numbers in tables.
- **Deltas** follow semantic colour: green for positive movement, red for
  negative, muted grey for flat/neutral. Always pair colour with an arrow
  glyph so the meaning survives greyscale printing.
- **Progress bars:** accent-colour fill on a subtle background track
  (`background: var(--track); border-radius: 999px;`). Height 6–8px. No
  gradients, stripes, or animations.
- **Sparklines:** inline SVG, 60–80px wide, 20–24px tall. Area fill at
  ~15% opacity, stroke at full accent. No axes, no gridlines, no labels.
- **Formatting:** thousands separators for counts, one decimal for
  percentages, currency symbols applied consistently across all cards.

## Design Rules

- **Every KPI must have a comparison** — versus last period or versus
  target. A number with no reference point is not a KPI.
- **Consistent number formatting** across all slides: same decimal places,
  same units, same separators.
- **Colour is semantic only.** Green = good, red = bad, yellow = caution,
  accent = neutral/graphical. Do not use colour to decorate headings,
  backgrounds, or borders.
- **No decorative elements.** No icons for decoration, no illustrations, no
  gradients, no drop shadows, no emoji.
- **One idea per slide.** Same layout grammar throughout; vary content, not
  structure.
- Slides are full-viewport `<section>` elements with scroll-snap; support
  arrow-key navigation and hash sync.

## Do Not

- Do not use lorem ipsum metrics or filler sentences in card descriptions.
- Do not invent data. Any unavailable metric is written exactly as
  `[NEEDS DATA]` — never estimate, never average, never fabricate a delta.
- Do not include decorative charts, pie charts, or 3D effects. Sparklines
  and progress bars are the only charts.
- Do not exceed **8 items** in any list, column, or table. If there are more,
  roll the rest into "and N more" or split into a second slide.

## Implementation

- Single-file HTML: inline `<style>` and `<script>`, no external CSS/JS/font
  requests (reference `Inter` with fallbacks only).
- Keyboard navigation: `ArrowDown`/`ArrowRight`/`PageDown` advance,
  `ArrowUp`/`ArrowLeft`/`PageUp` go back, `Home`/`End` jump to first/last.
- Hash sync: on load, read `location.hash` (`#3`) to open that slide; update
  the hash as slides change so the deck is linkable.
- Slide count is driven by the data — a typical weekly report is 5–8 slides.
- Mark any missing metric as `[NEEDS DATA]`.
