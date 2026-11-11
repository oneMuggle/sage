# Academic Design System

> A conservative, authoritative design system for academic publishing — theses,
> dissertations, journal articles, conference proceedings, and research papers.
> Inspired by the visual language of Nature, Science, IEEE, and university
> style guides worldwide.

---

## 1. Visual Theme

### Mood & Personality

- **Formal** — serious, scholarly, trustworthy
- **Authoritative** — conveys expertise and rigor
- **Conservative** — no decorative flourishes, no visual noise
- **Timeless** — built to look correct for decades, not seasons

### Design Philosophy

Academic design serves one master: **readability of long-form scholarly content**.
Every decision prioritises the reader's ability to absorb dense technical material
without distraction. Ornamentation is withheld. Hierarchy is conveyed through
typography alone. Colour is used sparingly and deliberately.

The system draws from three traditions:

1. **Academic journals** — Nature, Science, The Lancet, JAMA
2. **University style guides** — Oxford, Harvard, MIT thesis formatting requirements
3. **Typesetting standards** — Chicago Manual of Style, APA 7th, IEEE referencing

### Emotional Tone

| Attribute    | Value                                      |
|------------- |--------------------------------------------|
| Seriousness  | High — this is not a playful or casual system |
| Trust        | Very high — evokes peer review and rigour  |
| Warmth       | Low — cool, objective, impersonal          |
| Energy       | Low — static, contemplative, unhurried     |
| Complexity   | Moderate — structured but not ornate       |

---

## 2. Color Palette

The academic palette is deliberately restrained. Colour carries meaning only
when it must: links, headings, and citation markers. Everything else is
black-on-white.

### Core Colors

| Token                  | Hex       | Usage                                    |
|------------------------|-----------|------------------------------------------|
| `--academic-bg`        | `#ffffff` | Page background — pure white              |
| `--academic-text`      | `#222222` | Body text — near-black, softer than pure  |
| `--academic-heading`   | `#1a1a1a` | Headings — slightly darker than body      |
| `--academic-accent`    | `#1a3a5c` | Links, heading accents, figure rules      |
| `--academic-muted`     | `#666666` | Captions, footnotes, page numbers         |
| `--academic-rule`      | `#cccccc` | Table borders, horizontal rules           |
| `--academic-light-bg`  | `#f5f5f5` | Shaded table cells, box backgrounds       |

### Semantic Colors (used sparingly)

| Token                    | Hex       | Usage                          |
|--------------------------|-----------|--------------------------------|
| `--academic-error`       | `#990000` | Correction marks, error states |
| `--academic-success`     | `#2e5e2e` | Verification indicators        |
| `--academic-warning`     | `#7a5e00` | Caution markers                |
| `--academic-info`        | `#1a3a5c` | Same as accent — information   |

### Palette Principles

- **No warm tones in the base palette.** Warm colours (reds, oranges, ambers)
  appear only as semantic signals (error, warning) and are muted, never vibrant.
- **Dark blue is the sole accent.** `#1a3a5c` evokes ink, authority, institutional
  branding. It appears in links, section headings, and figure/table numbering.
- **High contrast is mandatory.** Body text (`#222222` on `#ffffff`) yields a
  contrast ratio of 15.4:1 — well above WCAG AAA (7:1).
- **No gradients.** Academic content is flat. Gradients suggest marketing, not
  scholarship.
- **Colour must earn its place.** If an element can be conveyed through weight,
  size, or position alone, do not add colour.

---

## 3. Typography

Typography is the backbone of academic design. The system uses a **serif
body / sans-serif heading** contrast — the most traditional pairing in
scholarly publishing.

### Font Stacks

| Role             | Primary              | Fallback                           |
|------------------|----------------------|------------------------------------|
| Body (serif)     | `Times New Roman`    | `Noto Serif`, `Georgia`, `serif`   |
| Headings (sans)  | `Arial`              | `Helvetica`, `Helvetica Neue`, `sans-serif` |
| Code (mono)      | `Courier New`        | `Consolas`, `monospace`            |
| Captions (sans)  | `Arial`              | `Helvetica`, `sans-serif`          |

### Type Scale (6 levels)

The scale is optimised for print-like reading at typical desktop distances.
Base size is 12pt (16px) — the standard for academic manuscripts.

| Level     | Size (px) | Size (pt) | Weight  | Line Height | Usage                        |
|-----------|-----------|-----------|---------|-------------|------------------------------|
| `display` | 28        | 21        | 700     | 1.2         | Paper title, thesis title    |
| `h1`      | 22        | 16.5      | 700     | 1.3         | Major section (1. Introduction) |
| `h2`      | 18        | 13.5      | 700     | 1.3         | Subsection (1.1 Background)  |
| `h3`      | 16        | 12        | 700     | 1.4         | Sub-subsection (1.1.1 Scope) |
| `body`    | 16        | 12        | 400     | 1.5         | Body text, abstract, bibliography |
| `caption` | 13        | 9.75      | 400     | 1.4         | Figure/table captions, footnotes |

### Typographic Rules

- **Line height: 1.5** (the academic standard, equivalent to "double spacing"
  in manuscript conventions).
- **Paragraphs** are separated by `1.5em` margin, not indented. Alternatively,
  first-line indent of `2em` may be used — but not both simultaneously.
- **Headings** are left-aligned, never centred (except the paper title).
- **Lists** use decimal numbering (`1.`, `1.1.`, `1.1.1.`) in formal contexts.
  Bullet lists use solid circles (`●`) for first level, open circles (`○`) for
  second.
- **Block quotes** are indented `2em` on both sides, with no quotation marks.
- **Footnotes** appear at the bottom of the page (or section), in `caption`
  size, separated by a 1px rule spanning one-third of the page width.
- **Citations** use numeric format `[1]` or author-date `(Smith, 2024)`
  depending on the referencing style.
- **Page numbers** appear centred at the footer, or outer-margin for
  double-sided printing.

---

## 4. Spacing System

Spacing is derived from the body line height, not a pixel grid. This ensures
vertical rhythm is maintained across all elements — a critical concern in
print and print-like layouts.

### Base Unit

The base unit is **1 line height** = `24px` (16px body × 1.5 line-height).

| Token           | Value  | Multiple | Usage                                |
|-----------------|--------|----------|--------------------------------------|
| `--space-xs`    | `6px`  | 0.25x    | Tight internal padding (tag chips)   |
| `--space-sm`    | `12px` | 0.5x     | Cell padding, compact gaps           |
| `--space-md`    | `24px` | 1x       | Paragraph margins, list item gaps    |
| `--space-lg`    | `36px` | 1.5x     | Between sections                     |
| `--space-xl`    | `48px` | 2x       | Between major sections               |
| `--space-2xl`   | `72px` | 3x       | Page-level separation, chapter breaks|

### Spacing Principles

- **Vertical rhythm is sacred.** Every element's margin and padding should be
  a multiple of the base unit (24px) or its halves.
- **Whitespace communicates structure.** Generous spacing between sections
  replaces decorative dividers.
- **No arbitrary pixel values.** If a spacing value cannot be expressed as a
  multiple of 6px, it does not belong in this system.

---

## 5. Component Stylings

### Buttons

Buttons in academic design are understated. The primary interaction pattern is
the **underlined text link**, not a filled button.

| Variant        | Style                                                      |
|----------------|------------------------------------------------------------|
| Primary link   | `--academic-accent` text, `1px solid underline`, no border-radius |
| Secondary link | `--academic-accent` text, no underline until hover         |
| Action button  | `1px solid --academic-accent` border, transparent fill, 2px border-radius |
| Disabled       | `--academic-muted` text, `opacity: 0.5`, no pointer       |

### Tables

Tables follow academic convention: **full borders** or **three-line style**
(horizontal rules above, below header, and below table body only).

**Three-line style (preferred for data tables):**

```
─────────────────────────────────
 Variable      Mean      SD
─────────────────────────────────
 Age           34.2      8.7
 Score         78.4      12.1
─────────────────────────────────
```

- Header row: bold, with rules above and below
- Data rows: no vertical rules, alternating row shading optional
- Caption: below the table, in `caption` size, prefixed with "Table 1:"
- Cell padding: `--space-sm` vertical, `--space-md` horizontal

### Figures

- Figures are **centred** within the content column.
- A thin rule (`1px solid --academic-rule`) appears above and below the figure.
- **Caption appears BELOW the figure** (never above), in `caption` size,
  prefixed with "Figure 1:" in bold.
- Figures are numbered sequentially per section or globally.
- Maximum width: 100% of content column.

### Equations

- Display equations are **centred** with equation numbers right-aligned
  in parentheses: `(1)`, `(2)`, etc.
- Inline equations use italic serif.
- Vertical spacing around display equations: `--space-md` above and below.

### Citations & References

- In-text citations: `[1]` (numeric) or `(Smith, 2024)` (author-date).
- Reference list: hanging indent (`2em`), `caption` size, sorted
  alphabetically or by citation order.
- DOI links: rendered as plain URLs, not hyperlinked text.

### Footnotes & Endnotes

- Superscript numerals in body text.
- Footnote area separated by a short rule (one-third page width).
- Footnote text in `caption` size, single-spaced.

---

## 6. Layout

### Content Column

| Context             | Max Width | Margins             | Notes                    |
|---------------------|-----------|---------------------|--------------------------|
| Journal article     | `720px`   | Auto-centred        | Single column            |
| Conference paper    | `680px`   | Auto-centred        | Slightly narrower        |
| Two-column proceedings | `1200px` | Two `560px` cols, `40px` gutter | IEEE/ACM style |
| Thesis / dissertation | `720px` | `40mm` inner margin | Binding margin           |

### Grid System

- **Single column** for standard papers (the default).
- **Two column** for proceedings and specific journal formats.
- **No asymmetric grids.** Academic layouts are symmetrical and predictable.
- **Full-bleed elements** (tables, figures) may extend to column edges only.

### Page Structure

```
┌─────────────────────────────────────┐
│  Running head (optional)            │  ← --space-sm from top
├─────────────────────────────────────┤
│                                     │
│  Title                              │  ← --space-xl from header
│  Authors / Affiliations             │
│  Abstract                           │
│                                     │
│  1. Introduction                    │  ← --space-xl between sections
│  Body text...                       │
│                                     │
│  1.1. Background                    │  ← --space-lg between subsections
│  Body text...                       │
│                                     │
│  ┌─────────────────────┐           │
│  │    Figure 1          │           │
│  └─────────────────────┘           │
│  Figure 1: Caption below.           │
│                                     │
│  2. Methods                         │
│  ...                                │
│                                     │
├─────────────────────────────────────┤
│  References                         │  ← --space-2xl before
│  [1] Author (2024). Title...        │
│  [2] Author (2023). Title...        │
├─────────────────────────────────────┤
│              12                     │  ← Page number, centred
└─────────────────────────────────────┘
```

### Binding Margins

For print theses, the inner (gutter) margin must accommodate binding:

| Side   | Margin  |
|--------|---------|
| Inner  | `40mm`  |
| Outer  | `25mm`  |
| Top    | `25mm`  |
| Bottom | `25mm`  |

---

## 7. Do's

- **Use numbered headings.** `1. Introduction`, `1.1. Background`, `1.1.1. Scope`.
  Numbering aids navigation in long documents.
- **Use figure and table numbering.** `Figure 1`, `Table 2` — sequential across
  the entire document.
- **Use formal citation format.** Follow the target style guide (APA, IEEE,
  Chicago) consistently throughout.
- **Use Times New Roman (or Noto Serif) for body text.** Serif fonts guide the
  eye along lines of dense prose.
- **Use page numbers.** Every page must be numbered. Use `Page X of Y` format
  for multi-page documents.
- **Use consistent heading hierarchy.** Never skip levels (e.g., h1 → h3
  without h2).
- **Use italics for emphasis, not bold.** In academic writing, bold is reserved
  for headings. Emphasis within body text uses italics.
- **Use high-contrast colour.** If colour is used, it must meet WCAG AAA.
- **Use captions for all visual elements.** No figure, table, or equation
  should appear without a descriptive caption.
- **Use whitespace generously.** Let the content breathe. Academic readers
  expect — and need — visual rest.

---

## 8. Don'ts

- **No decorative elements.** No flourishes, ornaments, dingbats, or clip art.
  Every visual element must serve an informational purpose.
- **No coloured backgrounds.** Backgrounds are white. The only exception is
  `--academic-light-bg` for shaded table cells or boxed content.
- **No informal language.** Avoid contractions, slang, emojis, or colloquial
  phrasing in any visible text.
- **No sans-serif body text.** Body text must be serif. Sans-serif is reserved
  for headings, captions, and UI controls.
- **No images without captions.** Every image is a "Figure" and must have a
  numbered caption below it.
- **No drop shadows.** Shadows suggest depth and interactivity. Academic
  content is flat and static.
- **No rounded corners on content containers.** Tables, figures, and blocks
  use sharp `0px` or minimal `2px` border-radius.
- **No gradient backgrounds.** Gradients are decorative. Academic design does
  not decorate.
- **No animations or transitions.** Content is consumed at the reader's pace.
  Motion is unnecessary and distracting.
- **No sticky headers or floating elements.** The layout is static and
  paginated, like print.
- **No bold for emphasis within body text.** Use italics.
- **No exclamation marks.** Academic prose is declarative, not exclamatory.
- **No first-person pronouns** (in formal contexts). Use "this paper" or "the
  authors" instead of "we" or "I".

---

## 9. Accessibility

- **Contrast ratio:** Body text achieves 15.4:1 (WCAG AAA). Accent colour
  `#1a3a5c` on `#ffffff` achieves 9.8:1 (WCAG AAA).
- **Font size:** 16px body text exceeds the 12px minimum for readability.
- **Line height:** 1.5 exceeds the 1.5 WCAG recommendation.
- **Focus indicators:** Use `outline: 2px solid --academic-accent` with
  `outline-offset: 2px` for keyboard navigation.
- **Link identification:** Links must be distinguishable by more than colour
  alone — use underline in addition to the accent colour.

---

## 10. Implementation Notes

- This system is designed for **static, paginated content**. Components should
  not include hover states beyond subtle underline changes.
- **Print stylesheet** should be near-identical to the screen stylesheet —
  the screen version is already print-like.
- **Dark mode** is intentionally not supported in the base system. Academic
  content is consumed in well-lit environments. If dark mode is required,
  invert to `#1a1a1a` background and `#e0e0e0` text, keeping the same accent.
- **Responsive behaviour** should be limited to width adjustments. The layout
  should never become multi-column on mobile — reduce to single column with
  the same max-width constraint.
- **Font loading:** Preload `Times New Roman` / `Noto Serif` to avoid FOUT
  (Flash of Unstyled Text). Use `font-display: swap` as fallback.

---

## 11. Comparison with Other Systems

| Attribute          | Academic         | Modern SaaS      | Editorial        |
|--------------------|------------------|------------------|------------------|
| Body font          | Serif            | Sans-serif       | Serif            |
| Heading font       | Sans-serif       | Sans-serif       | Serif or display |
| Line height        | 1.5              | 1.4–1.6          | 1.3–1.5          |
| Accent colour      | Dark blue only   | Multiple         | Brand-dependent  |
| Shadows            | None             | Common           | Minimal          |
| Border radius      | 0–2px            | 4–12px           | 0–4px            |
| Animations         | None             | Common           | Minimal          |
| Column layout      | 1 or 2 fixed     | Fluid grid       | Asymmetric       |
| Max content width  | 720px            | 960–1200px       | 680–800px        |
| Primary interaction| Underlined links | Filled buttons   | Mixed            |

---

## 12. Token Reference

All design tokens are defined in `tokens.css`. The token namespace is
`--academic-*` to avoid collisions with other systems.

Key token categories:

- `--academic-color-*` — colour palette
- `--academic-font-*` — font families and weights
- `--academic-text-*` — font sizes, line heights, letter spacing
- `--academic-space-*` — spacing scale
- `--academic-border-*` — border widths, styles, radii
- `--academic-shadow-*` — intentionally empty (no shadows)
- `--academic-transition-*` — intentionally empty (no transitions)

See `tokens.css` for the complete token reference.
