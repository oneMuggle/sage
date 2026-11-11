---
id: checklist
name: Delivery Checklist
description: Self-review before delivering an artifact. P0 blocks, P1 should pass, P2 is polish.
applies_to: both
priority: 3
---

# Delivery Checklist

Run this top to bottom before emitting the `<artifact>`. P0 must pass; P1 should
pass; P2 is bonus.

## P0 -- must pass (block delivery)

- [ ] **No lorem ipsum / placeholder copy.** Every string is real or marked
      `[NEEDS DATA]`.
- [ ] **No invented metrics.** Numbers are sourced or flagged.
- [ ] **No emoji icons.** Icons are inline SVG or typographic.
- [ ] **No default indigo accent.** The accent is brand-specific.
- [ ] **Body text contrast 4.5:1 or higher.** Checked against the actual background.
- [ ] **Semantic HTML.** `header` / `nav` / `main` / `section` / `footer`,
      headings in order (no `h1` -> `h4` jumps).
- [ ] **No broken references.** No `href="#"` masquerading as a real link unless
      it is a documented stub.
- [ ] **Craft rules followed.** anti-ai-slop P0 list cleared.

## P1 -- should pass

- [ ] Type scale is 4-6 sizes on a multiplicative ratio.
- [ ] Accent used 3 times or fewer per screen.
- [ ] Spacing is consistent (one grid, grouped by proximity).
- [ ] Interactive elements have hover + focus states.
- [ ] One display size per screen; hierarchy uses weight + size.
- [ ] Responsive: layout holds at 375px, 768px, 1280px.

## P2 -- polish

- [ ] Empty states for data views.
- [ ] Loading states for async regions.
- [ ] `prefers-reduced-motion` respected.
- [ ] Print stylesheet for decks.
- [ ] Images have alt text (or are marked decorative).

## Decks specifically

- [ ] Slide titles read as a coherent argument when skimmed in order.
- [ ] One idea per slide; body 5 bullets or fewer / 40 words or fewer.
- [ ] Speaker notes present where the slide under-explains.
- [ ] Projection legibility: title 2.5rem+, body 1.25rem+, high contrast.
