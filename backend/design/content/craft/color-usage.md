---
id: color-usage
name: Color Usage
description: Structure a palette around neutrals and spend accent color deliberately.
applies_to: both
priority: 1
---

# Color Usage

Color is a budget. Most of it should be neutral; accent is spend.

## The 70-20-10 structure

- **70-90% neutrals** -- backgrounds, surfaces, body text, borders.
- **5-20% secondary** -- muted tints, section backgrounds, dividers.
- **5-10% accent** -- the one hue that means "act here" or "this matters".

If accent appears more than **2-3 times per screen**, it stops meaning anything.

## Accent discipline

- One accent hue per artifact. Not two competing accents.
- Accent marks: the primary CTA, the active nav item, one key data point. That is it.
- Never use accent as a background fill for large areas unless it is a deliberate
  brand moment (a hero band), and then desaturate it.

## Contrast (non-negotiable)

- Body text vs background: **4.5:1 or higher** (WCAG AA).
- Large text (24px+ or 18.66px bold): **3:1 or higher**.
- UI borders and icons: **3:1 or higher** against their adjacent color.
- Never ship grey body text below 4.5:1 because it "looks elegant". It is
  unreadable for a large fraction of users.

## Semantic color

- Green = positive/success, Red = negative/error, Amber = warning. Use them
  **only** for those meanings. A decorative green is a lie.
- Never rely on color alone to convey meaning -- pair with an icon, label, or
  shape (color-blind safety).

## Dark mode

- Invert the neutral ramp, don't invert the hex. Dark surfaces are near-black
  (`#0a0a0a`-`#1a1a1a`), not pure `#000`. Pure black + pure white text vibrates.
- Reduce accent saturation slightly in dark mode; saturated hues glow.
- Shadows are invisible on dark -- use borders or surface-lightening for elevation.

## Don'ts

- Don't invent a hue outside the design system's palette.
- Don't use gradients to substitute for hierarchy.
- Don't put colored text on a colored background without checking contrast.
