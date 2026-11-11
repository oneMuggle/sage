# Startup Design System

> A bold, energetic design system for startups and pitch materials.
> Inspired by Stripe, Linear, Vercel landing pages.
> Mood: ambitious, modern, fast-moving.

---

## 1. Visual Theme

The Startup system communicates confidence and momentum. It uses oversized typography,
vibrant gradient accents on a clean white canvas, and generous whitespace to create
a sense of ambition and clarity. Every element should feel intentional and forward-leaning.

**Core adjectives:** bold, confident, energetic, modern, ambitious.

**Reference aesthetics:**

- Stripe.com — clean layout with colorful gradient accents
- Linear.app — dark headings, crisp typography, subtle shadows
- Vercel.com — large hero type, high contrast, geometric precision
- Rauno Freiberg's portfolio — subtle glow effects, refined spacing

---

## 2. Color Palette

### Background

| Token | Hex | Usage |
|---|---|---|
| `--startup-bg` | `#ffffff` | Primary page background |
| `--startup-bg-subtle` | `#f8fafc` | Alternate section backgrounds (very light slate) |
| `--startup-bg-muted` | `#f1f5f9` | Card hover, input backgrounds |

### Text

| Token | Hex | Usage |
|---|---|---|
| `--startup-text-heading` | `#0f172a` | Headlines, primary headings (deep slate) |
| `--startup-text-body` | `#334155` | Body text, paragraphs |
| `--startup-text-muted` | `#64748b` | Captions, secondary text |
| `--startup-text-inverted` | `#ffffff` | Text on dark/gradient backgrounds |

### Accent — Gradient Primary

The signature gradient is **purple-to-blue**, used on CTAs, highlights, and key
interactive elements. Define as two variables so it can be used in
`linear-gradient(var(--startup-gradient-start), var(--startup-gradient-end))`.

| Token | Hex | Usage |
|---|---|---|
| `--startup-gradient-start` | `#7c3aed` | Gradient start (violet-600) |
| `--startup-gradient-end` | `#2563eb` | Gradient end (blue-600) |

### Accent — Secondary

| Token | Hex | Usage |
|---|---|---|
| `--startup-accent-emerald` | `#10b981` | Success states, positive metrics |
| `--startup-accent-amber` | `#f59e0b` | Warnings, highlights, star ratings |
| `--startup-accent-rose` | `#f43f5e` | Alerts, negative metrics |

### Border

| Token | Hex | Usage |
|---|---|---|
| `--startup-border` | `#e2e8f0` | Default borders |
| `--startup-border-strong` | `#cbd5e1` | Emphasized borders |

---

## 3. Typography

**Font family:** `Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`

The Startup system uses a geometric sans-serif at large display sizes. Type should
feel confident and commanding — never timid.

### Scale (8-level)

| Level | Size | Line Height | Letter Spacing | Weight | Usage |
|---|---|---|---|---|---|
| Display | 4rem (64px) | 1.05 | -0.03em | 800 | Hero headlines |
| Hero | 3rem (48px) | 1.1 | -0.025em | 700 | Section heroes |
| H1 | 2.25rem (36px) | 1.15 | -0.02em | 700 | Page titles |
| H2 | 1.875rem (30px) | 1.2 | -0.015em | 700 | Section headings |
| H3 | 1.5rem (24px) | 1.25 | -0.01em | 600 | Subsection headings |
| H4 | 1.25rem (20px) | 1.3 | -0.005em | 600 | Card titles |
| Body | 1rem (16px) | 1.6 | 0 | 400 | Body text |
| Small | 0.875rem (14px) | 1.5 | 0.01em | 500 | Captions, labels |

### Rules

- Hero and Display sizes use negative letter-spacing for tight, confident feel
- Headlines are **never** below weight 600
- Body text is 400-500 weight — never bold body text
- Line heights tighten at larger sizes (1.05 at display, 1.6 at body)
- **No serif fonts anywhere** — this is a strictly geometric/modern system

---

## 4. Spacing

**Grid:** 8px base unit.

| Token | Value | Usage |
|---|---|---|
| `--space-1` | 4px | Micro adjustments |
| `--space-2` | 8px | Inline gaps, icon padding |
| `--space-3` | 12px | Small component padding |
| `--space-4` | 16px | Default component padding |
| `--space-5` | 20px | Card padding (compact) |
| `--space-6` | 24px | Card padding, section gaps (tight) |
| `--space-8` | 32px | Section gaps |
| `--space-10` | 40px | Component group separation |
| `--space-12` | 48px | Section padding (top/bottom) |
| `--space-16` | 64px | Large section padding |
| `--space-20` | 80px | Hero section padding |
| `--space-24` | 96px | Feature section padding |
| `--space-30` | 120px | Hero sections (generous) |
| `--space-36` | 144px | Landing page hero (maximum) |
| `--space-40` | 160px | Maximum section padding |

### Rules

- Hero sections use `space-30` to `space-40` padding (120-160px)
- Cards use `space-5` to `space-6` internal padding (20-24px)
- Alternating sections have generous vertical rhythm
- Never use spacing below `space-2` (4px) except for hairline adjustments

---

## 5. Component Stylings

### Buttons

**Primary (Gradient)**

```css
background: linear-gradient(135deg, var(--startup-gradient-start), var(--startup-gradient-end));
color: #ffffff;
border: none;
border-radius: 8px;
padding: 12px 28px;
font-weight: 600;
font-size: 1rem;
transition: all 200ms ease-out;
box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
```

Hover state: add glow effect — `box-shadow: 0 0 24px rgba(124, 58, 237, 0.35)`
and slight translateY(-1px).

**Secondary (Outline)**

```css
background: transparent;
color: var(--startup-text-heading);
border: 1.5px solid var(--startup-border-strong);
border-radius: 8px;
padding: 12px 28px;
font-weight: 600;
```

Hover: border-color shifts to gradient-start, background picks up subtle tint.

**Ghost**

```css
background: transparent;
color: var(--startup-text-body);
border: none;
padding: 8px 16px;
```

### Cards

```css
background: #ffffff;
border: 1px solid var(--startup-border);
border-radius: 12px;
padding: 24px;
box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04), 0 1px 2px rgba(0, 0, 0, 0.02);
transition: all 200ms ease-out;
```

Hover: `box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08)` + `translateY(-2px)`.

**Feature cards** may have a top gradient border accent (3px gradient top-border
via `::before` pseudo-element).

### Badges

```css
background: #ede9fe; /* violet-100 */
color: #5b21b6; /* violet-700 */
border-radius: 9999px;
padding: 4px 12px;
font-size: 0.75rem;
font-weight: 600;
letter-spacing: 0.02em;
```

Variants: emerald (`#d1fae5` / `#065f46`), amber (`#fef3c7` / `#92400e`),
rose (`#ffe4e6` / `#9f1239`).

### CTA Sections

Large, full-width sections with contrasting backgrounds to drive action.

**Light variant:** `--startup-bg-subtle` background, heading + paragraph + button.
**Dark variant:** deep slate (`#0f172a`) background, white text, gradient button.
**Gradient variant:** gradient background, white text, white outlined button.

### Metrics / Stats

Use animated counters for key numbers. Large display-size numerals with small
labels beneath. Arrange in 3-up or 4-up grids with dividers between.

### Social Proof

Logo rows (grayscale, 50% opacity), testimonial cards with avatar + quote + name,
"Trusted by" sections with large client logos.

### Before / After Comparisons

Side-by-side panels with muted "before" (grey tones) and vibrant "after"
(gradient accents, elevated shadow). A vertical divider or arrow between panels.

---

## 6. Layout

### Grid

- **Content max-width:** 1200px, centered with `margin: 0 auto`
- **Grid columns:** 12-column CSS grid with 24px gutters
- **Page padding:** 24px on mobile, 48px on tablet, 80px on desktop

### Section Patterns

- **Full-width alternating:** sections span 100vw with alternating `--startup-bg`
  and `--startup-bg-subtle` backgrounds; content constrained to 1200px
- **Hero pattern:** full-viewport minimum height (80vh), centered content,
  large display type, gradient accent on key word or CTA
- **Feature grid:** 3-column card layout on desktop, 2 on tablet, 1 on mobile
- **Split section:** 50/50 text + visual, alternating left/right per section

### Responsive Breakpoints

| Name | Width | Columns |
|---|---|---|
| Mobile | < 640px | 4 |
| Tablet | 640-1024px | 8 |
| Desktop | > 1024px | 12 |

---

## 7. Do's

- **Use gradient accents sparingly** — one or two gradient elements per viewport;
  let the gradient feel special, not omnipresent
- **Use large hero typography** — Display/Hero sizes for first-fold impact;
  type should command attention immediately
- **Use social proof sections** — logo rows, testimonial cards, "trusted by" blocks;
  credibility is essential for startup materials
- **Use animated counters for metrics** — numbers that count up draw the eye and
  communicate traction (e.g., "10,000+ users", "$2M raised")
- **Use before/after comparisons** — especially for product demos; show transformation
- **Maintain generous whitespace** — let elements breathe; whitespace communicates
  confidence and premium quality
- **Use subtle shadows for depth** — multi-layer shadows create a refined, modern feel
- **Keep visual hierarchy sharp** — heading sizes should have clear jumps; never
  ambiguous between H2 and H3
- **Use color semantically** — emerald for success/growth, amber for attention,
  rose for decline/alert

---

## 8. Don'ts

- **No serif fonts** — this system is strictly geometric/modern sans-serif;
  serifs break the energetic, forward-looking mood
- **No conservative colors** — avoid navy-only, grey-only, or muted palettes;
  the gradient accent is non-negotiable
- **No small timid type** — body text is 16px minimum; headlines are 36px+;
  never use 12px headlines or 14px heroes
- **No walls of text without visual breaks** — every 3-4 lines of text needs a
  visual interrupt (image, icon, stat, card, quote)
- **No generic stock-photo-style layouts** — avoid centered-image-with-text-on-both-sides;
  prefer asymmetric layouts, overlapping elements, gradient backgrounds
- **No heavy borders** — 1px borders maximum; never 2px+ solid borders on containers
- **No drop shadows with high opacity** — shadows should be subtle and layered;
  avoid `box-shadow: 0 4px 20px rgba(0,0,0,0.3)` or similar
- **No more than 2 fonts** — Inter + optional monospace for code; never introduce
  a third typeface
- **No centered paragraphs wider than 65ch** — long-form text must be constrained
  for readability

---

## 9. Animation & Motion

| Property | Duration | Easing | Usage |
|---|---|---|---|
| Hover state | 200ms | ease-out | Buttons, cards, links |
| Section reveal | 300ms | ease-out | Fade-in on scroll |
| Counter animation | 600ms | ease-out | Metric count-up |
| Page transition | 300ms | ease-in-out | Route changes |

**Principle:** motion should feel snappy and responsive. Never sluggish. 200ms is
the default; 300ms for larger transitions. Never exceed 400ms.

---

## 10. Accessibility

- All text must meet WCAG 2.1 AA contrast ratios (4.5:1 body, 3:1 large text)
- Gradient text must have a solid fallback for reduced-motion preferences
- Focus states: 2px solid outline in `--startup-gradient-start`, offset 2px
- Interactive elements must have visible hover/focus states
- Animated counters must respect `prefers-reduced-motion`
