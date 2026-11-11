---
id: typography-hierarchy
name: Typography Hierarchy
description: Build a type scale with contrast, rhythm, and restraint.
applies_to: both
priority: 1
---

# Typography Hierarchy

Hierarchy is the difference between "designed" and "text on a page".

## The scale

Use a **multiplicative scale**, not arbitrary sizes. Pick a ratio and commit:

- Editorial / display-heavy: ratio **1.333** (perfect fourth)
- UI / dense content: ratio **1.2** (minor third)

A 1.2 scale from 16px: `16 -> 19 -> 23 -> 28 -> 33 -> 40 -> 48`.
A 1.333 scale from 16px: `16 -> 21 -> 28 -> 38 -> 50 -> 67`.

Most artifacts need **4-6 sizes**, not 10. If you reach for a 7th size, your
hierarchy is doing too little with weight and spacing.

## Weight is half the hierarchy

- Use **weight contrast** before size contrast. A 600 body next to a 400 body
  reads as hierarchy without adding a size.
- Display headings: 600-800. Body: 400-500. Never bold body copy -- it flattens
  the scale.

## Line height

- **Display (32px+):** 1.1-1.2. Tight. Big type needs less leading.
- **Body (16-20px):** 1.5-1.7. Comfortable reading.
- **Dense UI (14px or less):** 1.4-1.5. Don't go below 1.4 on dense text.

## Letter spacing

- **Display (40px+):** negative tracking, `-0.02em` to `-0.03em`. Big letters
  need to come closer.
- **Body:** neutral, `0`.
- **Small caps / kickers / labels:** positive tracking, `0.05em` to `0.12em`,
  uppercase.

## Rules

- One display size per screen. Don't compete two 48px headlines.
- Paragraph measure: **45-75 characters** per line. Cap `max-width` in `ch` units.
- Never use more than **two font families**. One is often enough.
- CJK text needs slightly looser line-height (+0.05) and no tight negative tracking.
