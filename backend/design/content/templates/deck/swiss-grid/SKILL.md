---
name: swiss-grid
kind: deck
description: "Swiss International Style deck: 16-column grid, 22 locked layouts, 4 color themes (Klein Blue, Lemon, Neon, Safety). Grid-anchored, monochrome accents."
design_system_required: true
---

# Swiss Grid Template

Swiss International Style (International Typographic Style) deck template.
Every element is anchored to a 16-column grid. Color is monochrome with a
single accent. Typography is Helvetica-family. Layout is determined by
content structure, not ornament.

## Intent

Use this template for:

- Corporate presentations, board reviews, annual reports
- Data-driven decks where numbers lead the argument
- International audiences — neutral typography, no cultural references
- Strategy, research, systems, and technical work

The deck must feel clean, rational, and systematic. Nothing on a slide exists
for ornament. If an element does not carry information, remove it.

## Grid System

- Canvas: 1920 × 1080 (16:9)
- 16-column grid — each column is 120px at the 1920px design width (1920 ÷ 16)
- 80px gutters (column gaps and the outer margin on every side)
- Content begins and ends on column boundaries — no free-floating placement
- Vertical rhythm in multiples of 8px; 80px between major zones
- Every element spans a whole number of columns
- The grid scales together with the canvas; ratios are preserved on resize

## Color Themes

Each deck uses a monochrome base plus one accent. Choose a single theme per
deck and never mix accents.

| Theme | Ink | Paper | Accent | Notes |
| --- | --- | --- | --- | --- |
| Klein Blue | `#000000` | `#ffffff` | `#002FA7` | Yves Klein blue — classic Swiss accent |
| Lemon Yellow | `#000000` | `#ffffff` | `#F5D547` | Warm signal, restrained use |
| Neon Green | `#000000` | `#ffffff` | `#39FF14` | High energy, use for emphasis only |
| Safety Orange | `#000000` | `#ffffff` | `#FF5F1F` | Alert-level emphasis |

Rules of use:

- Accent appears on one element per slide — a bar, a number, a rule, a mark.
  Never more.
- Accent occupies at most ~10% of slide surface area.
- Neutrals remain pure black, white, and greys derived from black (opacity or
  pure grey values); no tinted neutrals.

## Typography

- Faces: `"Helvetica Neue", Helvetica, Arial, sans-serif`
- Never use decorative, script, serif display, or novelty faces
- Display sizes (64–144px): weight 700–900, `letter-spacing: -0.03em` to
  `-0.05em`, tight tracking
- Body (18–28px): weight 100–200, `line-height: 1.3`–`1.45`
- Section labels: 12–14px, **uppercase**, `letter-spacing: 0.16em`–`0.20em`,
  weight 700
- Numbers/data: tabular numerals (`font-variant-numeric: tabular-nums`),
  40–96px, weight 700–900
- Sentence case for headlines; uppercase only for short labels and meta lines
- Avoid italics — use weight and scale for hierarchy
- Weight contrast is the primary signal: 800 for headlines, 200 for body

## Layout Types

22 locked layouts distributed across eight families. Pick one layout per
slide; stay on-column.

| # | Family | Use | Structure |
|---| --- | --- | --- |
| 1 | **Title** | Deck opening | Kicker + display + subtitle + byline; accent rule |
| 2 | **Section Divider** | Chapter break | One short uppercase label, 2–4 words; no body |
| 3 | **Text-Heavy** | Narrative / argument | Headline + 6–8 col body; pull quote or footnote in second column |
| 4 | **Data / Chart** | Numbers | Headline + chart/table (10–16 cols) + one enlarged stat + source |
| 5 | **Quote** | Voice / principle | Quote spanning 8–12 cols; attribution; no other content |
| 6 | **Image Full-Bleed** | Visual evidence | Edge-to-edge image or 12–16 cols; one caption anchored to grid |
| 7 | **Split Screen** | Two arguments | 8/8 or 6/10 column split; shared baseline |
| 8 | **Grid Gallery** | Multiple visuals | 2×2, 3×2, or 4×4 image grid on column boundaries |

## Design Rules

- Everything aligns to the 16-column grid
- One idea per slide — never two competing claims
- Monochrome by default; accent used only for data emphasis
- Generous whitespace between zones (≥ 80px between major blocks)
- Page numbers in a consistent position on every slide
- Rules and hairlines are structural — use them to separate content, not to
  decorate
- Charts: flat bars, no 3D, no shadows; label data directly, not with legends
- Images: black-and-white or duotone preferred
- Hierarchy comes from scale and weight, not color
- 8–15 slides is the normal range for a corporate deck

## Never

- Gradients
- Drop shadows
- Rounded corners (`border-radius: 0` everywhere)
- Illustrations, clip art, icon packs, emoji
- Decorative or novelty fonts
- Multiple accent colors or tinted backgrounds
- Full sentences in uppercase
- Centered body paragraphs (centering reserved for title, section, quote)
- Animation that delays reading (no transitions on text)

## Technical Requirements

- Single self-contained HTML file — inline CSS and JS, no external fonts or
  dependencies
- Full-viewport `<section>` slides, one slide per screen, `scroll-snap-type:
  y mandatory`
- Keyboard navigation: arrows, `Space`, `PageUp` / `PageDown`, `Home` /
  `End`
- Hash sync: every slide has an `id`; the URL hash updates on navigation;
  deep links load the correct slide on first paint
- Page number: bottom-right, `NN / TT`, tabular numerals, identical position
  on every slide
- Scale: design at 1920 × 1080; scale gracefully on smaller viewports
  without breaking grid spans
- Semantic HTML (`<section>`, `<blockquote>`, `<header>`); `aria-label` on
  charts rendered as `img`
- Print-friendly: `@media print` should give one page per slide

## Content Guidelines

- Use realistic placeholder content, never lorem ipsum
- Headlines are assertions, not noun phrases
- Mark missing data as `[NEEDS DATA]` instead of inventing numbers
- Cite every number; source line at the bottom of data slides
- ≤ 40–80 words of body per slide
- Keep numeric formatting consistent within a deck (percent notation, decimal
  separator, thousand separator)

## Example

See `example.html` for a three-slide Klein Blue deck covering Title,
Data / Chart, and Quote layouts.
