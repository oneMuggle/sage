---
id: animation-discipline
name: Animation Discipline
description: Motion should explain a change, not decorate it.
applies_to: both
priority: 2
---

# Animation Discipline

Motion earns its place only when it **explains a state change**. Decorative
animation is a liability: it distracts, it costs performance, and it dates fast.

## When motion is justified

- **Entering content** -- content sliding/fading in on first load or scroll,
  once, fast (150-300ms).
- **State change** -- a button's press feedback, a toggle flipping, a panel
  opening. The motion shows what changed.
- **Spatial relationship** -- a modal zooming from the button that opened it, a
  card expanding into a detail view. The motion shows where it came from.
- **Progress** -- a determinate bar filling. The motion shows how much is left.

## When it is not

- Content bouncing, wiggling, or pulsing for attention.
- Parallax on every scroll.
- Staggered fade-in of every item "just because".
- Infinite looping animations in a content surface.

## Rules

- **Duration:** 150-250ms for micro-interactions, 250-400ms for larger
  transitions. Nothing over 500ms in a UI.
- **Easing:** `ease-out` for entering, `ease-in` for exiting, `ease-in-out` for
  on-screen movement. Avoid `linear` except for progress/rotation.
- **Budget:** at most **3 distinct animations** per screen. More is noise.
- **Respect `prefers-reduced-motion`.** Wrap all non-essential motion in
  `@media (prefers-reduced-motion: no-preference)`.
- Animate `transform` and `opacity` only. Never animate `width`/`height`/`top`/
  `left` -- they trigger layout and jank.

## Decks

Slide transitions should be a single, consistent mechanism (fade, or a short
translate). Do not mix transition styles across a deck.
