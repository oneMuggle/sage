# Editorial Design System

> A magazine-grade design system emphasizing narrative clarity, typographic refinement,
> and the quiet confidence of premium print editorial. Inspired by Monocle, FT Magazine,
> and The New York Times.

---

## 1. Visual Theme

**Mood:** Sophisticated, narrative, calm, authoritative.

**Metaphor:** Premium print magazine on warm paper. Ink that breathes. Whitespace that speaks.

**Core principles:**

- Typography is the primary design element — not decoration
- Whitespace is a structural component, not empty space
- Restraint signals confidence — ornament is earned, not applied
- Hierarchy is established through scale, weight, and spacing — not color explosion
- Content deserves reverence; the system recedes to let narrative lead

**Avoid at all costs:** Anything that screams "digital interface." No gradients. No drop
shadows. No rounded corners. No saturated neon. This is paper, not pixel.

---

## 2. Color Palette

The editorial palette is built on warm paper tones and deep ink, with a single muted accent
evoking burnt sienna — the color of a typesetter's proof mark.

### 2.1 Backgrounds

| Token | Hex | Usage |
|-------|-----|-------|
| `bg` | `#faf8f5` | Page background — warm paper white |
| `bg-subtle` | `#f3f0eb` | Section differentiation — slightly aged paper |
| `bg-muted` | `#ebe6de` | Pull quote backgrounds, aside blocks |
| `bg-inverse` | `#1a1a1a` | Dark feature sections (rare, full-bleed) |

### 2.2 Foregrounds

| Token | Hex | Usage |
|-------|-----|-------|
| `fg` | `#1a1a1a` | Primary body text — near-black ink |
| `fg-muted` | `#6b6560` | Secondary text, captions, bylines |
| `fg-subtle` | `#9a948c` | Tertiary text, timestamps, footnotes |
| `fg-inverse` | `#faf8f5` | Text on inverse backgrounds |

### 2.3 Accents

| Token | Hex | Usage |
|-------|-----|-------|
| `primary` | `#a0522d` | Burnt sienna — links, rules, key accents |
| `primary-hover` | `#8b4526` | Hover state for primary |
| `primary-muted` | `#c4896b` | Subtle accent tints, tag backgrounds |
| `primary-subtle` | `#f0e4db` | Highlight backgrounds, selection |

### 2.4 Semantic (muted, never saturated)

| Token | Hex | Usage |
|-------|-----|-------|
| `success` | `#5a7a5a` | Sage green — editorially appropriate |
| `warning` | `#b8860b` | Dark goldenrod — aged paper warning |
| `error` | `#8b3a3a` | Muted crimson — not alarm-red |
| `info` | `#4a6b8a` | Slate blue — restrained information |

---

## 3. Typography

Typography is the soul of the editorial system. Two type families do all the work:
a serif for display and emphasis, a humanist sans for body and UI.

### 3.1 Font Stacks

**Display (serif):**

```
--ds-editorial-font-display: 'Playfair Display', 'Noto Serif SC', 'Source Han Serif SC',
                              'Source Han Serif', Georgia, 'Times New Roman', serif;
```

**Body (sans):**

```
--ds-editorial-font-body: 'Inter', 'Noto Sans SC', 'Source Han Sans SC',
                          -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
```

**Mono (code, data):**

```
--ds-editorial-font-mono: 'JetBrains Mono', 'Source Code Pro', 'Fira Code',
                          Consolas, 'Courier New', monospace;
```

### 3.2 Type Scale (8 levels)

| Level | Name | Size | Line Height | Letter Spacing | Weight | Usage |
|-------|------|------|-------------|----------------|--------|-------|
| 1 | `display-xl` | 4rem / 64px | 1.1 | -0.02em | 700 | Hero headlines, cover titles |
| 2 | `display-lg` | 3rem / 48px | 1.15 | -0.02em | 700 | Feature headlines |
| 3 | `display-md` | 2.5rem / 40px | 1.2 | -0.015em | 600 | Section titles |
| 4 | `display-sm` | 2rem / 32px | 1.25 | -0.01em | 600 | Article titles |
| 5 | `heading` | 1.5rem / 24px | 1.3 | -0.01em | 600 | Subheadings, deck heads |
| 6 | `body-lg` | 1.125rem / 18px | 1.7 | 0 | 400 | Lead paragraphs, pull quotes |
| 7 | `body` | 1rem / 16px | 1.7 | 0.005em | 400 | Body text, paragraphs |
| 8 | `caption` | 0.875rem / 14px | 1.5 | 0.01em | 400 | Captions, footnotes, metadata |

### 3.3 Typographic Conventions

- **Display sizes (levels 1-4):** Always serif. Tight letter-spacing for gravitas.
- **Body text (levels 6-7):** Always sans-serif. Generous line-height (1.7) for readability.
- **Emphasis:** Use serif italics (`Playfair Display Italic`) for pull quotes, not bold.
- **Kickers / overlines:** Small-caps, letter-spacing 0.08em, primary color.
- **Drop caps:** First letter of article open — 3 lines tall, serif, floated left.
- **Numbers:** Use tabular lining figures for data; old-style figures for narrative.

---

## 4. Spacing

The editorial system uses an 8px base grid, but with significantly more generous
section-to-section spacing than UI-focused systems. Whitespace is a feature, not waste.

### 4.1 Base Grid

| Token | Value | Usage |
|-------|-------|-------|
| `space-1` | 4px | Micro adjustments, hairline padding |
| `space-2` | 8px | Inline icon gaps, tight padding |
| `space-3` | 12px | Component internal padding |
| `space-4` | 16px | Standard component padding |
| `space-5` | 24px | Card padding, list item spacing |
| `space-6` | 32px | Between related components |
| `space-7` | 48px | Between content groups |
| `space-8` | 64px | Between major sections |
| `space-9` | 80px | Between feature sections |
| `space-10` | 120px | Between narrative acts / chapters |

### 4.2 Editorial Spacing Rules

- **Paragraph spacing:** 1.5em (inherited from line-height, no margin needed)
- **Section breaks:** Minimum 80px (space-9) between major narrative sections
- **Article padding:** 48px (space-7) top/bottom on mobile, 80px on desktop
- **Pull quote margin:** 48px (space-7) above and below
- **Byline to body:** 24px (space-5)

---

## 5. Borders & Rules

Editorial design uses hairline rules (1px) to separate content, never shadows or fills.

### 5.1 Border Styles

| Token | Value | Usage |
|-------|-------|-------|
| `border-hairline` | `1px solid var(--ds-editorial-color-border)` | Section dividers |
| `border-rule` | `1px solid var(--ds-editorial-color-fg)` | Strong emphasis rules |
| `border-accent` | `2px solid var(--ds-editorial-color-primary)` | Accent rules, active states |
| `border-thick` | `3px solid var(--ds-editorial-color-fg)` | Feature separators (rare) |

### 5.2 Border Radius

**All border-radius values are 0.** Editorial design does not use rounded corners.
Sharp corners signal print provenance and typographic discipline.

| Token | Value |
|-------|-------|
| `radius-none` | 0 |
| `radius-default` | 0 |
| `radius-lg` | 0 |

---

## 6. Shadows

**No shadows.** Editorial depth is achieved through:

- Hairline rules (1px borders)
- Background tone shifts (bg → bg-subtle → bg-muted)
- Typography scale contrast
- Whitespace isolation

There is zero elevation in the editorial system. Everything sits on the same plane — the page.

---

## 7. Component Stylings

### 7.1 Buttons

Buttons are minimal and typographic. Primary actions are underlined text links with
optional small-caps labels. Secondary actions are plain text.

**Primary button:**

- Background: transparent
- Border: none
- Color: `primary`
- Text-decoration: underline (1px, `primary`)
- Text-transform: none
- Padding: 8px 0
- Hover: color `primary-hover`, text-decoration-thickness 2px

**Secondary button:**

- Background: transparent
- Border: none
- Color: `fg`
- Text-decoration: none
- Hover: text-decoration underline

**Outlined button (rare):**

- Background: transparent
- Border: 1px solid `fg`
- Color: `fg`
- Padding: 12px 24px
- Hover: background `fg`, color `bg`

### 7.2 Cards

Cards are defined by whitespace and hairline rules, never shadows.

- Background: `bg` or `bg-subtle`
- Border: 1px solid `border` (or no border if whitespace-separated)
- Border-radius: 0
- Padding: 24px–32px
- No box-shadow

### 7.3 Inputs

- Background: transparent
- Border-bottom: 1px solid `border`
- Border-radius: 0
- Padding: 12px 0
- Focus: border-bottom-color `primary`, border-bottom-width 2px
- No box-shadow, no outline

### 7.4 Navigation

- Hairline bottom border (1px solid `border`)
- Logo in serif display, nav items in sans body
- Active indicator: 2px bottom border in `primary`
- No background fills, no shadows

### 7.5 Pull Quotes

- Font: serif display italic
- Size: `body-lg` (1.125rem) or `heading` (1.5rem)
- Color: `fg`
- Left border: 3px solid `primary`
- Padding-left: 24px
- Margin: 48px vertical

### 7.6 Drop Caps

- First letter of article open
- Font: serif display
- Size: 3x line-height
- Float: left
- Padding-right: 8px
- Line-height: 1

---

## 8. Layout

### 8.1 Content Widths

| Context | Max-width | Usage |
|---------|-----------|-------|
| Article body | 800px | Optimal reading measure |
| Magazine grid | 1200px | Multi-column feature layouts |
| Full-bleed | 100% | Hero images, pull quotes |
| Narrow aside | 480px | Sidebars, captions |

### 8.2 Grid Systems

**Article layout:**

- Single column, max-width 800px
- Centered with auto margins
- Generous padding: 24px mobile, 48px tablet, 80px desktop

**Magazine grid:**

- 12-column grid at 1200px
- Gutters: 24px
- Can nest article extracts, feature cards, pull quotes

### 8.3 Responsive Breakpoints

| Token | Value | Usage |
|-------|-------|-------|
| `breakpoint-sm` | 640px | Mobile landscape |
| `breakpoint-md` | 768px | Tablet portrait |
| `breakpoint-lg` | 1024px | Tablet landscape, small desktop |
| `breakpoint-xl` | 1280px | Desktop |
| `breakpoint-2xl` | 1536px | Large desktop |

---

## 9. Transitions & Animation

Animation is subtle and purposeful — never bouncy or playful.

| Token | Value | Usage |
|-------|-------|-------|
| `transition-fast` | 150ms ease | Hover states |
| `transition-base` | 200ms ease | Default transitions |
| `transition-slow` | 400ms ease | Page transitions, fades |

**Allowed animations:**

- Fade (opacity)
- Slide (transform: translateY)
- Underline expansion (text-decoration)

**Forbidden animations:**

- Bounce
- Elastic / spring
- Scale (except hover: 1.0 → 1.02 on cards, very rare)
- Rotation

---

## 10. Do's

- **Use drop caps** for article opens — they signal narrative beginning
- **Use small-caps** for kickers, overlines, and category labels
- **Use hairline rules** (1px) to separate sections — never double rules except feature heads
- **Use serif italics** for pull quotes — italic serif = editorial voice
- **Use generous whitespace** — if in doubt, add more
- **Use burnt sienna sparingly** — it's a spice, not the main ingredient
- **Use tabular figures** for data tables and financial content
- **Use deck heads** (subheadings in larger serif) to bridge headline and body
- **Use bylines in small-caps** with letter-spacing for author attribution
- **Let typography breathe** — resist the urge to fill space

---

## 11. Don'ts

- **No gradients** — ever. Not even subtle ones. Paper doesn't gradient.
- **No drop shadows** — depth comes from rules and tone shifts
- **No rounded corners** — sharp corners are print DNA
- **No emoji decoration** — if you need emoji, you've failed at typography
- **No sans-serif headlines** — headlines are serif, always
- **No saturated accent colors** — no neon, no electric blue, no hot pink
- **No colored backgrounds for CTAs** — use underlined text or hairline borders
- **No heavy borders** — hairline rules, never 3px+ except rare feature separators
- **No skeleton loaders with rounded rectangles** — use editorial placeholders
  (italic text: "Loading...")
- **No sticky footers with elevation** — the page is flat
- **No gradient text** — ink is one color
- **No floating action buttons** — everything sits on the page

---

## 12. Accessibility

- **Contrast ratios:** All text must meet WCAG AA (4.5:1 body, 3:1 display)
- **Focus states:** 2px solid underline in `primary`, offset 2px
- **Link identification:** Always underlined in body text; contextual in navigation
- **Font scaling:** Support user font-size preferences (use rem throughout)
- **Reduced motion:** Respect `prefers-reduced-motion` — disable all animations

---

## 13. Usage Examples

### Article Header

```
[small-caps kicker: FEATURE] in primary color

[display-lg serif headline: The Future of Typography]

[body-lg serif italic deck: How a centuries-old craft is being reborn in digital form]

[byline: BY JANE DOE | NOVEMBER 2026] in small-caps, muted color

— hairline rule —

[body text begins with drop cap]
```

### Pull Quote

```
[left border 3px primary]
[serif italic, body-lg]
"Typography is the craft of endowing human language with a durable visual form."
[caption, muted] — Robert Bringhurst
```

### Magazine Grid

```
[12-column grid, 1200px max]
[col 1-8: Feature article extract with hairline rule below]
[col 9-12: Sidebar with 3 related stories, hairline-separated]
```

---

## 14. Brand Personality

If the editorial system were a person:

- Well-read, widely traveled, quietly confident
- Prefers quality over quantity
- Speaks in complete sentences
- Wears tailored clothes, never logos
- Owns a well-worn notebook
- Orders the same drink at the same café
- Values substance over spectacle

---

## 15. System Token Prefix

All tokens use the prefix `--ds-editorial-` to avoid collision with other design systems.

Example usage:

```css
.headline {
  font-family: var(--ds-editorial-font-display);
  font-size: var(--ds-editorial-typography-display-lg);
  color: var(--ds-editorial-color-fg);
  letter-spacing: var(--ds-editorial-typography-tracking-tight);
}
```

---

*This system is a canvas for stories, not a showcase for itself.*
