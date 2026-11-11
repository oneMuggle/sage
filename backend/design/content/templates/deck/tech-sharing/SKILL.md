---
name: tech-sharing
kind: deck
description: "Technical sharing deck: code blocks with syntax highlighting, architecture diagrams in CSS/SVG, data comparisons, and demo slides. Dark or light mode."
design_system_required: true
---

# Tech Sharing Deck Template

Generate an HTML slide deck for technical talks, conference presentations,
internal engineering sharing, and tutorials. Slides are full-viewport
`<section>` elements stacked vertically, navigated with arrow keys and
scroll snapping. Code blocks feature syntax highlighting; architecture
diagrams are drawn with CSS boxes and arrows (no images).

## Intent

- Tech talks and conference presentations
- Internal engineering sharing sessions
- Technical tutorials and walkthroughs
- Architecture reviews and design proposals
- Post-mortem and retrospective presentations

## Modes

The template supports two color modes, controlled by adding class
`mode-dark` (default) or `mode-light` to the `<body>` element.

| Mode   | Background | Foreground | Notes                          |
|--------|------------|------------|--------------------------------|
| dark   | `#1a1a2e`  | `#e8e8f0`  | Default. Best for projection.  |
| light  | `#ffffff`  | `#1a1a2e`  | Alternative for print/bright rooms. |

## Typography

- **UI text**: Inter (fallback: system sans-serif)
- **Code**: JetBrains Mono, Fira Code (fallback: monospace)
- **Display (slide titles)**: 2.5rem - 3rem
- **Body text**: 1.125rem - 1.25rem
- **Code**: 0.9rem - 1rem with 1.5 line-height

## Layout Types (10)

### L01 Title

Talk title + speaker name + event/date + optional avatar.

- Title: 3rem, centered or left-aligned
- Speaker name with optional role/title line
- Event name and date in muted color
- Optional circular avatar (CSS-drawn placeholder if no image)

### L02 Agenda

Numbered list with time estimates.

- Each item: number, topic, duration estimate
- Example: "01  Architecture overview  (10 min)"
- Use horizontal rule or flex row to separate items
- 3-7 items maximum

### L03 Section

Big section title + one-line description.

- Section title: 2.75rem, bold
- One-line description in muted color below
- Used to transition between major parts of the talk

### L04 Code Block

Full-slide code with line numbers and syntax highlighting.

- Dark code background: `#161616`
- Line numbers in muted color (`#6a6a8a`) on the left
- Monospace font, 0.9rem - 1rem, 1.5 line-height
- **Maximum 20 lines per slide** -- split longer code across multiple slides
- Keyword, string, comment, function, number color scheme (see Code Styling)
- Optional language label in top-right corner (e.g., "Python", "TypeScript")
- Highlighted lines (for emphasis) get a subtle background bar

### L05 Code Compare

Side-by-side before/after code or two approaches.

- Two code panels, each with its own language label
- Dividing gutter with "VS" or arrow
- Each panel max 15 lines to keep readable
- Use color to reinforce: red-tinted border for "before", green-tinted for "after"

### L06 Architecture

CSS/SVG diagram boxes with arrows. **No images.**

- Boxes drawn with CSS (border, border-radius, background)
- Arrows via CSS pseudo-elements or inline SVG
- Clear labels inside boxes
- Connection lines show data/control flow direction
- Use consistent box sizes for same-layer components
- Keep to 2-3 layers (e.g., client / service / storage)

### L07 Data Comparison

Bar chart or table comparing metrics.

- Horizontal CSS bar charts (no external chart libraries)
- Bars drawn with div + width percentage
- Labels to the left, values to the right of bars
- Comparison table alternative: 2-4 columns, striped rows
- Annotate the delta or percentage change when comparing

### L08 Demo

Large screenshot placeholder (CSS-drawn) + caption.

- Placeholder box with dashed border or gradient fill
- CSS-drawn browser chrome (title bar with dots)
- Caption below: what this demonstrates, one sentence
- Optional step callouts numbered on the screenshot

### L09 Key Takeaway

3-5 bullet points, large type.

- Each point: 1.25rem - 1.5rem, with left accent bar
- Maximum 5 points; prefer 3
- Use bold for the key phrase in each point
- No paragraphs; one line per point

### L10 Q&A

Large "?" + contact info + repo link.

- Giant question mark or "Q & A" as display element
- Speaker name and contact (email, Twitter, etc.)
- Repository or resource URL
- Optional: QR code (CSS-drawn placeholder)

## Code Styling

All code blocks use a dark background with syntax highlighting colors:

| Token          | Color (dark bg)   | Color (light bg)  |
|----------------|-------------------|-------------------|
| Background     | `#161616`         | `#f5f5fa`         |
| Line numbers   | `#6a6a8a`         | `#9999aa`         |
| Keywords       | `#c678dd`         | `#7c3aed`         |
| Strings        | `#98c379`         | `#16a34a`         |
| Comments       | `#5c6370`         | `#6b7280`         |
| Functions      | `#61afef`         | `#2563eb`         |
| Numbers        | `#d19a66`         | `#d97706`         |
| Operators      | `#56b6c2`         | `#0891b2`         |
| Punctuation    | `#abb2bf`         | `#4b5563`         |

Apply syntax classes: `.tok-kw` (keyword), `.tok-str` (string),
`.tok-cmt` (comment), `.tok-fn` (function), `.tok-num` (number),
`.tok-op` (operator), `.tok-punc` (punctuation).

## Design Rules

1. **Code readability**: code must be readable from the back of a room.
   Minimum 0.9rem code font size; 1rem preferred for conference stages.
2. **Architecture diagrams**: use CSS boxes + arrows, never images.
   Diagrams must be legible at 50% zoom on a projector.
3. **Code density**: maximum 20 lines per code slide. If the code is longer,
   split across multiple slides (label them "Part 1/2" etc.).
4. **No walls of text**: max 5 bullets or 40 words per non-code slide.
5. **High contrast**: avoid grey-on-grey; projected decks wash out.
6. **Consistent rhythm**: one layout grammar per slide; vary emphasis,
   not structure.

## Forbidden

- Decorative animations (fade-ins, bounce, parallax) -- they distract
  from technical content
- Stock photos or generic imagery
- Lorem ipsum or obviously fake code -- use realistic code examples
- More than 3 font sizes on one slide
- Images for architecture diagrams (always CSS/SVG)

## Technical Requirements

- Single self-contained HTML file (inline CSS + JS, no external deps)
- Full-viewport slides with `scroll-snap-type: y mandatory`
- Keyboard navigation: Arrow keys, PageUp/PageDown, Home/End, Space
- Hash sync: URL updates to `#slide-N` on navigation; deep-linkable
- Responsive: readable at 1920x1080 projector and 1366x768 laptop
- Semantic HTML: `<section>` per slide, `<h1>`/`<h2>` for titles
- Print-friendly: `@media print` should show one slide per page

## Content Guidelines

- Use realistic code examples relevant to the talk topic
- Mark any missing metric as `[NEEDS DATA]` rather than inventing numbers
- Keep slide titles as assertions, not noun phrases, when possible
- Code examples should be complete enough to be understood without
  verbal explanation (audience reads faster than speaker talks)
