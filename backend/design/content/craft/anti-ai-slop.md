---
id: anti-ai-slop
name: Anti-AI-Slop
description: Reject the visual tells of machine-generated design. Applies to every output.
applies_to: both
priority: 0
---

# Anti-AI-Slop

AI-generated design has a fingerprint. Strip it out.

## Cardinal sins (P0 -- never ship)

- **Default Tailwind indigo** (`#6366f1` / `indigo-500`) as the accent. It is the single
  most recognizable AI tell. Pick a brand-specific accent instead.
- **Trust gradients** -- purple-to-blue or pink-to-orange backgrounds behind a hero.
  If a gradient has no semantic job, delete it.
- **Emoji as icons.** A rocket for "fast", a lock for "secure". Use inline SVG or
  a typographic glyph. Never an emoji in a production surface.
- **Rounded card with a colored left border** (the "callout card" cliche). Pick one
  emphasis mechanism, not two stacked.
- **Three identical feature cards** with icon-title-blurb and nothing else. Vary the
  rhythm or use a different section type.
- **Invented metrics.** `99.9% uptime`, `10x faster`, `500K users` with no source.
  Mark unknown numbers as `[NEEDS DATA]` instead of fabricating.

## Soft tells (P1 -- avoid)

- Every section centered. Introduce asymmetry and left-alignment.
- `border-radius: 12px` on everything. Pick one radius scale and respect it.
- Drop shadows on every card. Elevation must mean something.
- Generic placeholder copy: "Lorem ipsum", "Your headline here", "Feature one".
- Perfectly even spacing with no grouping. Group related elements tighter.

## Polish tells (P2 -- nice to fix)

- No hover or focus states on interactive elements.
- No empty state for data views.
- Uniform font weight throughout -- hierarchy needs weight contrast.

## Enforcement

Before writing the `<artifact>`, scan your own plan against the P0 list. If any
item is present, change the design -- do not rationalize it as intentional.
