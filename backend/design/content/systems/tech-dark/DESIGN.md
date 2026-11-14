# Tech Dark Design System

> A dark-mode-first design system for technical content. Optimized for code blocks, architecture diagrams, and developer-facing interfaces.

## Visual Theme

**Mood:** Focused, modern, engineering-grade.
**Inspirations:** Linear, Vercel, GitHub Dark, Raycast.
**Keywords:** Precise, minimal, technical, high-contrast, developer-centric.

Tech Dark is built for interfaces where code and data take center stage. It prioritizes readability of monospaced content, clear visual hierarchy through subtle elevation changes, and restrained use of color. The overall effect should feel like a well-calibrated IDE or terminal — professional, quiet, and laser-focused on content.

---

## Color Palette

### Backgrounds (elevation layers)

| Token             | Hex       | Usage                                      |
|-------------------|-----------|--------------------------------------------|
| `--bg-base`       | `#0a0a0a` | Page-level background, root canvas          |
| `--bg-subtle`     | `#111111` | Card surfaces, section grouping             |
| `--bg-elevated`   | `#1a1a1a` | Hover states, dropdowns, modals, popovers   |
| `--bg-surface`    | `#161616` | Code blocks, terminal outputs, inline code  |
| `--bg-sunken`     | `#080808` | Inset areas, wells, disabled regions        |

### Foregrounds

| Token             | Hex       | Usage                                      |
|-------------------|-----------|--------------------------------------------|
| `--fg-primary`    | `#ededed` | Body text, headings, primary content        |
| `--fg-secondary`  | `#a1a1a1` | Secondary text, captions, labels            |
| `--fg-tertiary`   | `#666666` | Placeholders, disabled text, hints          |
| `--fg-inverse`    | `#0a0a0a` | Text on accent backgrounds (rare)           |

### Accent & Semantic

| Token             | Hex       | Usage                                      |
|-------------------|-----------|--------------------------------------------|
| `--accent-primary`   | `#06b6d4` | Cyan — CTAs, links, active states, focus rings |
| `--accent-secondary` | `#10b981` | Green — success, positive values, git additions |
| `--accent-warning`   | `#f59e0b` | Amber — warnings, cautions                |
| `--accent-error`     | `#ef4444` | Red — errors, destructive actions, git deletions |
| `--accent-info`      | `#3b82f6` | Blue — informational, neutral highlights  |

### Borders

| Token             | Hex       | Usage                                      |
|-------------------|-----------|--------------------------------------------|
| `--border-subtle` | `#1e1e1e` | Minimal separation, hairline dividers       |
| `--border-default`| `#2a2a2a` | Card borders, input borders, default edges  |
| `--border-strong` | `#3a3a3a` | Focus rings (with accent), active borders   |
| `--border-accent` | `#06b6d4` | Accent-colored borders for emphasis         |

---

## Typography

### Font Families

| Role          | Family             | Fallbacks                                       |
|---------------|--------------------|-------------------------------------------------|
| UI / Body     | `Inter`            | `-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif` |
| Code / Mono   | `JetBrains Mono`   | `"Fira Code", "Cascadia Code", "Consolas", monospace`       |
| Display (opt) | `Inter` (tight tracking) | Same as UI; use with `letter-spacing: -0.02em`         |

**Rule:** All technical values (hex colors, sizes, durations, file paths, commands, inline code) MUST use the monospace family. This creates a clear visual distinction between prose and technical content.

### Type Scale (8 levels, modular ~1.2 ratio)

| Level     | Size   | Line Height | Weight   | Tracking  | Usage                        |
|-----------|--------|-------------|----------|-----------|------------------------------|
| `text-xs` | 12px   | 16px        | 400      | 0         | Captions, labels, badges     |
| `text-sm` | 14px   | 20px        | 400      | 0         | Secondary text, code inline  |
| `text-base`| 16px  | 24px        | 400      | 0         | Body text default            |
| `text-md` | 18px   | 28px        | 500      | -0.01em   | Subheadings, emphasized body |
| `text-lg` | 20px   | 28px        | 600      | -0.01em   | Section headings (h3)        |
| `text-xl` | 24px   | 32px        | 600      | -0.015em  | Page headings (h2)           |
| `text-2xl`| 30px   | 36px        | 700      | -0.02em   | Feature headings (h1)        |
| `text-3xl`| 36px   | 40px        | 700      | -0.025em  | Hero / display (sparingly)   |

### Code Typography

- Inline code: `text-sm`, `--bg-surface` background, `--border-default` border, 2px 6px padding, 4px radius
- Code blocks: `text-sm`, `--bg-surface` background, 1px `--border-default` border, 16px padding, 6px radius
- Line numbers: `--fg-tertiary` color, right-aligned, 32px gutter, `user-select: none`
- Syntax highlighting: use a dedicated dark theme (e.g., One Dark, GitHub Dark Dimmed)

---

## Spacing

Tech Dark uses a **dual-grid system**:

- **4px grid** for tight UI: icon padding, inline elements, badge spacing, form field internals
- **8px grid** for content sections: card padding, section gaps, layout spacing

### Scale

| Token          | Value | Usage                                   |
|----------------|-------|-----------------------------------------|
| `space-0.5`    | 2px   | Micro adjustments, border offsets       |
| `space-1`      | 4px   | Icon-to-text gaps, inline padding       |
| `space-2`      | 8px   | Form field padding, list item gaps      |
| `space-3`      | 12px  | Card internal padding (compact)         |
| `space-4`      | 16px  | Card padding, section padding           |
| `space-5`      | 20px  | Form field height, input vertical pad   |
| `space-6`      | 24px  | Section gaps, group separation          |
| `space-8`      | 32px  | Page section spacing                    |
| `space-10`     | 40px  | Major section breaks                    |
| `space-12`     | 48px  | Page header/footer padding              |
| `space-16`     | 64px  | Hero spacing, feature sections          |

---

## Borders & Radius

### Border Widths

| Token             | Value | Usage                                   |
|-------------------|-------|-----------------------------------------|
| `border-thin`     | 1px   | Default for all containers, cards, inputs |
| `border-medium`   | 2px   | Focus rings, active states              |
| `border-thick`    | 4px   | Accent bars, progress indicators        |

### Border Radius

| Token            | Value | Usage                                   |
|------------------|-------|-----------------------------------------|
| `radius-sm`      | 4px   | Badges, tags, inline code, small chips  |
| `radius-default` | 6px   | Cards, buttons, inputs, modals          |
| `radius-md`      | 8px   | Large cards, panels, images             |

**Rule:** Never exceed 8px border radius. Tech Dark favors precise, engineering-grade corners over playful roundness. 6px is the workhorse radius — use it for 90% of components.

---

## Shadows & Effects

In dark mode, traditional drop shadows are nearly invisible. Tech Dark uses **subtle glow effects** and **border-based elevation** instead.

| Token              | Value                                         | Usage                     |
|--------------------|-----------------------------------------------|---------------------------|
| `shadow-sm`        | `0 1px 2px rgba(0, 0, 0, 0.4)`               | Subtle lift (cards)       |
| `shadow-default`   | `0 2px 8px rgba(0, 0, 0, 0.5)`               | Default elevation         |
| `shadow-lg`        | `0 8px 24px rgba(0, 0, 0, 0.6)`              | Modals, popovers          |
| `shadow-glow-sm`   | `0 0 12px rgba(6, 182, 212, 0.08)`           | Subtle accent glow        |
| `shadow-glow`      | `0 0 20px rgba(6, 182, 212, 0.1)`            | Active/focused accent glow|
| `shadow-glow-lg`   | `0 0 40px rgba(6, 182, 212, 0.15)`           | Prominent accent glow     |

**Rule:** Use `shadow-glow*` variants only on interactive elements in active/focus states. Do not apply glow to static content.

---

## Component Stylings

### Buttons

**Primary (CTA):**
- Background: `--accent-primary` (#06b6d4)
- Text: `--fg-inverse` (#0a0a0a), font-weight 600
- Border: none
- Radius: 6px
- Padding: 8px 16px
- Hover: brightness 110%, subtle glow `shadow-glow-sm`
- Active: brightness 95%
- Disabled: opacity 0.4, no pointer events

**Secondary:**
- Background: transparent
- Text: `--fg-primary`, font-weight 500
- Border: 1px `--border-default`
- Radius: 6px
- Padding: 8px 16px
- Hover: background `--bg-elevated`, border `--border-strong`
- Active: background `--bg-sunken`

**Ghost:**
- Background: transparent
- Text: `--fg-secondary`, font-weight 500
- Border: 1px transparent
- Radius: 6px
- Padding: 8px 12px
- Hover: background `--bg-subtle`, text `--fg-primary`

### Cards

- Background: `--bg-subtle` (#111111)
- Border: 1px `--border-default` (#2a2a2a)
- Radius: 6px
- Padding: 16px (standard) / 24px (content cards)
- No shadows by default (border provides separation)
- Hover (interactive cards): border `--border-strong`, subtle `shadow-sm`

### Code Blocks

- Background: `--bg-surface` (#161616)
- Border: 1px `--border-default` (#2a2a2a)
- Radius: 6px
- Padding: 16px
- Font: JetBrains Mono, 14px, line-height 1.7
- Line numbers: `--fg-tertiary`, gutter 32px, separated by 1px `--border-subtle` vertical line
- Header bar (optional): filename/language label in `--fg-tertiary`, 12px, uppercase, letter-spacing 0.05em, bottom border `--border-subtle`
- Copy button: ghost button, top-right corner, 28x28px

### Terminal Output

- Background: `--bg-sunken` (#080808)
- Border: 1px `--border-default`
- Radius: 6px
- Padding: 16px
- Font: JetBrains Mono, 14px
- Prompt character (`$`): `--accent-secondary` (green)
- Output text: `--fg-secondary`
- Error text: `--accent-error`
- Success text: `--accent-secondary`

### Inputs & Form Fields

- Background: `--bg-base` (#0a0a0a)
- Border: 1px `--border-default`
- Radius: 6px
- Padding: 8px 12px
- Font: Inter, 14px
- Placeholder: `--fg-tertiary`
- Focus: border `--accent-primary`, `shadow-glow-sm`
- Error: border `--accent-error`, no glow (red glow is aggressive)

### Navigation / Sidebar

- Background: `--bg-subtle` (#111111)
- Width: 240px (collapsed: 56px)
- Border-right: 1px `--border-default`
- Active item: background `--bg-elevated`, left border 2px `--accent-primary`, text `--fg-primary`
- Inactive item: text `--fg-secondary`, hover text `--fg-primary`, hover background `--bg-elevated`
- Section headers: `--fg-tertiary`, 12px, uppercase, letter-spacing 0.05em

---

## Layout

### Content Widths

| Context             | Max Width | Notes                              |
|---------------------|-----------|------------------------------------|
| Dashboard / App     | 100%      | Full-width, sidebar + content      |
| Documentation       | 960px     | Centered, generous side padding    |
| Article / Blog      | 720px     | Optimized for reading              |
| Code reference      | 1200px    | Wider for long code lines          |
| Settings / Forms    | 640px     | Compact, focused                   |

### Grid

- Dashboard grid: 12-column, 16px gap, 24px page padding
- Card grid: auto-fill, minmax(280px, 1fr), 16px gap
- Sidebar layout: 240px fixed sidebar + flexible content area

### Responsive Breakpoints

| Token       | Value  | Usage                              |
|-------------|--------|------------------------------------|
| `bp-sm`     | 640px  | Mobile, single column              |
| `bp-md`     | 768px  | Tablet, sidebar collapsible        |
| `bp-lg`     | 1024px | Desktop, sidebar expanded          |
| `bp-xl`     | 1280px | Wide desktop, max-width containers |
| `bp-2xl`    | 1536px | Ultra-wide, extra whitespace       |

---

## Transitions & Animation

| Token              | Duration | Easing                    | Usage                      |
|--------------------|----------|---------------------------|----------------------------|
| `transition-fast`  | 150ms    | `cubic-bezier(0.4, 0, 0.2, 1)` | Hover states, toggles      |
| `transition-base`  | 250ms    | `cubic-bezier(0.4, 0, 0.2, 1)` | Color changes, fades       |
| `transition-slow`  | 400ms    | `cubic-bezier(0.4, 0, 0.2, 1)` | Layout shifts, reveals     |

**Rules:**
- Never animate width/height directly; use `transform: scale()` or `max-height` with overflow hidden.
- Prefer `opacity` + `transform` for performance.
- Respect `prefers-reduced-motion`: disable all non-essential animation.

---

## Do's

- Use monospace (`JetBrains Mono`) for ALL technical values: hex codes, file paths, sizes, durations, commands, variable names, API endpoints
- Use subtle 1px borders (`--border-default`) for card and section separation instead of shadows
- Use the accent cyan (`--accent-primary`) SPARINGLY — only for CTAs, active states, links, and focus rings
- Use syntax-highlighted code blocks with line numbers for any code content
- Use elevation layers (base → subtle → elevated) to create visual hierarchy, not shadows
- Use `--fg-secondary` for captions and supporting text to maintain contrast hierarchy
- Use green (`--accent-secondary`) for success states, positive values, and "added" indicators
- Use 6px border radius consistently for a precise, engineering-grade feel
- Use 4px grid for internal component spacing, 8px grid for layout spacing
- Use Inter font-weight 600 for headings to maintain readability without heaviness

## Don'ts

- NO light backgrounds — this system is dark-mode only; do not add white or light gray surfaces
- NO serif fonts — they clash with the technical, modern aesthetic
- NO heavy shadows (`box-shadow: 0 10px 40px rgba(0,0,0,0.5)`) — dark mode makes them invisible; use glow or borders instead
- NO border radius greater than 8px — anything larger looks playful, not precise
- NO saturated background colors (e.g., full blue/green/red backgrounds) — use them only as text/accent colors on dark surfaces
- NO gradient text — it undermines the restrained, professional tone
- NO thick borders (>2px) except for accent bars or progress indicators
- NO mixed font families for code — always JetBrains Mono, never mix with Fira or Consolas
- NO opacity-based disabled states below 0.4 — content must remain legible
- NO animated backgrounds or particle effects — they distract from technical content
- NO colored shadows (e.g., `box-shadow: 0 0 20px blue`) except for the defined accent glow tokens
- NO text shadows — they reduce readability on dark backgrounds
