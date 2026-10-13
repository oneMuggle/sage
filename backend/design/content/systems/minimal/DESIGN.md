# Minimal Design System

A stripped-down design system that embraces constraints. No color distractions,
no shadows, no rounded corners — just content and structure.

## Visual Theme

The Minimal system is built on the principle that **content is the interface**.
Every decorative element is removed until only what the user needs remains.

- **Mood:** calm, focused, editorial
- **Contrast:** high (black on white)
- **Density:** comfortable, generous whitespace

## Color Palette

| Token | Value | Usage |
|-------|-------|-------|
| `--color-bg` | `#ffffff` | Page and card backgrounds |
| `--color-fg` | `#000000` | Primary text |
| `--color-muted` | `#666666` | Secondary text, captions |
| `--color-border` | `#cccccc` | Dividers, input borders |
| `--color-accent` | `#000000` | Links, buttons |
| `--color-error` | `#cc0000` | Error states |
| `--color-success` | `#006600` | Success states |

## Typography

- **Font stack:** `system-ui, -apple-system, "Segoe UI", sans-serif`
- **Base size:** 16px / `1rem`
- **Line height:** 1.5
- **Weights:** 400 (normal), 700 (bold)

### Scale

| Token | Size | Use |
|-------|------|-----|
| `--font-size-xs` | 12px | Footnotes, metadata |
| `--font-size-sm` | 14px | Secondary text |
| `--font-size-base` | 16px | Body text |
| `--font-size-lg` | 20px | Section headings |
| `--font-size-xl` | 24px | Page headings |
| `--font-size-2xl` | 32px | Hero / display |

## Spacing

Based on a **4px grid**. All spacing values are multiples of 4px.

| Token | Value |
|-------|-------|
| `--space-1` | 4px |
| `--space-2` | 8px |
| `--space-3` | 12px |
| `--space-4` | 16px |
| `--space-6` | 24px |
| `--space-8` | 32px |
| `--space-12` | 48px |
| `--space-16` | 64px |

## Component Stylings

- **Buttons:** solid black background, white text, no border-radius
- **Cards:** white background, 1px `--color-border` border, no shadow
- **Inputs:** 1px border, no border-radius, focus = 2px black outline
- **Links:** black, underlined, `--color-muted` on hover

## Layout

- Max content width: 720px (reading-optimized)
- Padding: `--space-4` on mobile, `--space-8` on desktop
- Grid: single column; multi-column only at `>= 1024px`

## Do's

- Do use generous whitespace to separate sections
- Do rely on typography scale for hierarchy
- Do use the border for structure, not decoration
- Do keep images and media full-bleed when possible

## Don'ts

- Don't add shadows — the system has none
- Don't use rounded corners — the system is square
- Don't introduce colors beyond the palette
- Don't use gradients or transparency effects
