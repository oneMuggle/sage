---
name: editorial-magazine
kind: deck
description: "Editorial magazine meets e-ink: 10 layouts and 5 palettes (Ink, Indigo, Forest, Kraft, Dune). Narrative, opinion, personal style expression."
design_system_required: true
---

# Editorial Magazine Deck Template

## Intent

This template produces magazine-style editorial decks inspired by Monocle, Financial Times, and print journalism aesthetics. It is designed for:

- Narrative storytelling and opinion pieces
- Sharing personal perspectives and essays
- Expressing individual style with a paper-like, print feel
- Content that should feel editorial, not technical or corporate

The visual language deliberately avoids tech-feel: no gradients, no glow, no rounded UI chrome. Instead, it evokes ink on paper — sharp typography, hairline rules, generous whitespace, and restrained color.

---

## Palettes (5 options)

Each palette defines four semantic color roles. All hex values are locked — do not invent new shades.

### 1. Ink Classic

| Role        | Hex       | Usage                              |
|-------------|-----------|------------------------------------|
| ink         | `#0a0a0b` | Primary text, hairline rules       |
| paper       | `#f1efea` | Slide background                   |
| paper-tint  | `#e8e5de` | Secondary panels, pull-quote bg    |
| ink-tint    | `#18181a` | Secondary text, captions, footers  |

### 2. Indigo Porcelain

| Role        | Hex       | Usage                              |
|-------------|-----------|------------------------------------|
| ink         | `#0a1f3d` | Primary text, hairline rules       |
| paper       | `#f1f3f5` | Slide background                   |
| paper-tint  | `#e4e8ec` | Secondary panels, pull-quote bg    |
| ink-tint    | `#152a4a` | Secondary text, captions, footers  |

### 3. Forest Ink

| Role        | Hex       | Usage                              |
|-------------|-----------|------------------------------------|
| ink         | `#1a2e1f` | Primary text, hairline rules       |
| paper       | `#f5f1e8` | Slide background                   |
| paper-tint  | `#ece7da` | Secondary panels, pull-quote bg    |
| ink-tint    | `#253d2c` | Secondary text, captions, footers  |

### 4. Kraft Paper

| Role        | Hex       | Usage                              |
|-------------|-----------|------------------------------------|
| ink         | `#2a1e13` | Primary text, hairline rules       |
| paper       | `#eedfc7` | Slide background                   |
| paper-tint  | `#e0d0b6` | Secondary panels, pull-quote bg    |
| ink-tint    | `#3a2a1d` | Secondary text, captions, footers  |

### 5. Dune

| Role        | Hex       | Usage                              |
|-------------|-----------|------------------------------------|
| ink         | `#1f1a14` | Primary text, hairline rules       |
| paper       | `#f0e6d2` | Slide background                   |
| paper-tint  | `#e3d7bf` | Secondary panels, pull-quote bg    |
| ink-tint    | `#2d2620` | Secondary text, captions, footers  |

---

## Layouts (10 types, L01-L10)

| Code | Name              | Structure                                                                 |
|------|-------------------|---------------------------------------------------------------------------|
| L01  | Hero Cover        | Full-bleed title, kicker above, subtitle below, folio bottom-right        |
| L02  | Act Divider       | Single large chapter/act label, centered, hairline top and bottom         |
| L03  | Big Numbers Grid  | 2x2 or 3x2 grid of oversized statistics with label and caption            |
| L04  | Quote+Image       | Pull quote left half, inline SVG illustration right half                  |
| L05  | Image Grid        | 2-3 inline SVG illustrations in a grid with captions underneath           |
| L06  | Pipeline/Flow     | Horizontal step flow with numbered stages and connecting hairlines        |
| L07  | Hero Question     | Single large question centered, optional small answer below               |
| L08  | Big Quote         | Full-slide pull quote, attribution bottom-right in ink-tint               |
| L09  | Before/After      | Two-column contrast layout with hairline divider down the center          |
| L10  | Mixed Media       | Asymmetric layout: text column + SVG illustration + pull-quote inset      |

---

## Typography

### Display (Headlines, Titles, Pull Quotes)

- **English**: Playfair Display (serif)
- **Chinese**: Noto Serif SC (serif)

### Body (Paragraphs, Captions, Labels)

- **English**: Inter (sans-serif)
- **Chinese**: Noto Sans SC (sans-serif)

### Magazine Details

- **Kicker** (category label above headline): `11px`, `uppercase`, `letter-spacing: 0.12em`, body font
- **Folio** (page number): bottom-right, `01/12` format, body font, ink-tint color
- **Top hairline rule**: 1px solid ink color, full width, appears on every slide except Hero Cover
- **Caption**: `12px`, ink-tint color, body font

---

## Design Rules (Hard Constraints)

The following are strictly **forbidden**. No exceptions.

- NO gradients (linear, radial, or conic)
- NO drop-shadow or box-shadow
- NO rounded corners (border-radius: 0 everywhere)
- NO circle decorations (only rectangles, lines, and inline SVG illustrations)
- NO blur (backdrop-filter or filter: blur)
- NO SVG icon libraries (inline SVG only, hand-drawn style)
- NO emoji decoration (text only, no emoji as visual elements)
- NO placeholder images (no picsum, no unsplash, no data URI photos)
- NO fake data or lorem ipsum — all content must be real or explicitly marked as user-provided
- NO animated transitions between slides (instant switch via hash)

### What to use instead

- **Visual interest**: inline SVG illustrations (geometric, editorial style)
- **Emphasis**: oversized typography, hairline rules, whitespace
- **Hierarchy**: size contrast, ink vs ink-tint, kicker labels
- **Texture**: paper-tint panels behind pull quotes, full-bleed ink sections for contrast

---

## Interaction

### Keyboard Navigation

- **Left Arrow** / **Right Arrow**: navigate between slides
- **Home**: first slide
- **End**: last slide

### Hash Sync

- Each slide has an ID: `#slide-01`, `#slide-02`, etc.
- On navigation, update `window.location.hash`
- On page load, read hash and jump to that slide
- This enables deep-linking to specific slides

### Single-File HTML

- All CSS is inline in `<style>` within `<head>`
- All JS is inline in `<script>` before `</body>`
- All SVG illustrations are inline in the HTML
- No external dependencies, no CDN links, no network requests
- Output is a single `.html` file that works offline

---

## Slide Count Guidance

The number of slides is determined by the user's content, not a fixed template length.

- **Short content** (essay, opinion): 6-12 slides
- **Long content** (feature story, report): 12-24 slides
- **Structure**: always start with L01 Hero Cover, use L02 Act Dividers to separate sections, end with a closing slide (L08 Big Quote or L07 Hero Question)

---

## CSS Variables Template

When generating the HTML, define palette colors as CSS custom properties on `:root`:

```css
:root {
  --ink: #0a0a0b;
  --paper: #f1efea;
  --paper-tint: #e8e5de;
  --ink-tint: #18181a;
}
```

All styling should reference these variables, not hardcoded hex values. This makes palette swapping trivial.

---

## Output Checklist

Before delivering the final HTML, verify:

- [ ] Single file, no external dependencies
- [ ] Palette colors match one of the 5 defined palettes exactly
- [ ] All 4 font faces are loaded (via @font-face with local() or system fallback)
- [ ] Keyboard navigation works (left/right/home/end)
- [ ] Hash sync works (deep link to #slide-03 loads that slide)
- [ ] No gradients, shadows, rounded corners, blur, or emoji
- [ ] All SVG illustrations are inline
- [ ] Folio numbers are present on every slide except Hero Cover
- [ ] Top hairline rule is present on every slide except Hero Cover
- [ ] No lorem ipsum or placeholder content
