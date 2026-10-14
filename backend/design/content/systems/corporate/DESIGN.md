# Corporate Design System

A professional, trustworthy design system for business applications. Built on
a blue-and-gray palette with the Inter typeface, 8px spacing grid, and subtle
shadows that create depth without distraction.

## Visual Theme

The Corporate system projects **stability, trust, and professionalism**. It is
designed for dashboards, reporting tools, and enterprise SaaS applications
where clarity and credibility matter most.

- **Mood:** professional, calm, trustworthy
- **Contrast:** moderate (dark navy on white, with blue accents)
- **Depth:** subtle shadows for layered UI (cards, modals, dropdowns)

## Color Palette

| Token | Value | Usage |
|-------|-------|-------|
| `--color-bg` | `#ffffff` | Primary backgrounds |
| `--color-bg-subtle` | `#f4f6f8` | Secondary / section backgrounds |
| `--color-fg` | `#1a1a2e` | Primary text |
| `--color-fg-muted` | `#5a6577` | Secondary text, captions |
| `--color-border` | `#d1d9e0` | Standard borders |
| `--color-primary` | `#1a56db` | Primary actions, links |
| `--color-primary-hover` | `#1648b8` | Primary hover state |
| `--color-primary-light` | `#e8effc` | Primary tint (badges, highlights) |
| `--color-accent` | `#0d9488` | Accent actions, tags |
| `--color-error` | `#dc2626` | Error states |
| `--color-success` | `#16a34a` | Success states |
| `--color-warning` | `#d97706` | Warning states |

## Typography

- **Font stack:** `"Inter", system-ui, -apple-system, "Segoe UI", sans-serif`
- **Base size:** 16px / `1rem`
- **Line height:** 1.6 (optimized for dense UI text)
- **Weights:** 400, 500 (medium), 600 (semibold), 700

### Scale

| Token | Size | Use |
|-------|------|-----|
| `--font-size-xs` | 12px | Labels, metadata |
| `--font-size-sm` | 14px | Table cells, secondary text |
| `--font-size-base` | 16px | Body text |
| `--font-size-lg` | 18px | Lead text, section titles |
| `--font-size-xl` | 20px | Page section headings |
| `--font-size-2xl` | 24px | Page title |
| `--font-size-3xl` | 30px | Dashboard hero |
| `--font-size-4xl` | 36px | Landing hero |

## Spacing

Based on an **8px grid**. All spacing values are multiples of 8px.

| Token | Value |
|-------|-------|
| `--space-1` | 8px |
| `--space-2` | 16px |
| `--space-3` | 24px |
| `--space-4` | 32px |
| `--space-5` | 40px |
| `--space-6` | 48px |
| `--space-8` | 64px |
| `--space-10` | 80px |
| `--space-12` | 96px |

## Component Stylings

- **Buttons (primary):** `--color-primary` background, white text, `--border-radius` (6px), `--shadow-xs`
- **Buttons (secondary):** white background, `--color-border` border, `--color-fg` text
- **Cards:** white background, `--border-radius` (6px), `--shadow-sm`, `--color-border-subtle` border
- **Inputs:** `--color-border` border, `--border-radius-sm` (4px), focus ring = 2px `--color-primary-light`
- **Tables:** `--color-bg-subtle` header row, `--color-border-subtle` row dividers
- **Links:** `--color-primary`, underline on hover

## Layout

- Max content width: 1200px (dashboard-optimized)
- Sidebar width: 240px (collapsible to 64px)
- Card padding: `--space-3` (24px)
- Page padding: `--space-4` (32px) on desktop, `--space-2` (16px) on mobile
- Grid: 12-column on desktop, single column on mobile

## Do's

- Do use shadows sparingly — only for elevated elements (cards, modals, dropdowns)
- Do use `--color-bg-subtle` to differentiate sections without heavy borders
- Do maintain 8px grid alignment for all spacing
- Do use font weights (500/600) for hierarchy within text-heavy UI
- Do provide loading and empty states for all data views

## Don'ts

- Don't use saturated colors outside the palette
- Don't mix border-radius values — stick to sm (4px), default (6px), lg (8px)
- Don't stack shadows — use only one shadow level per element
- Don't use all-caps labels — Inter looks best in sentence case
- Don't reduce line height below 1.4 — readability in dense UI depends on it
