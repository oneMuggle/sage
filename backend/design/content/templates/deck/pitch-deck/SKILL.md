---
name: pitch-deck
kind: deck
description: A minimal HTML slide deck with title, beats, evidence, and closer slides
design_system_required: true
---

# Pitch Deck Template

Generate an HTML slide deck. Slides are full-viewport `<section>` elements
stacked vertically, one slide per screen, navigated with arrow keys /
scroll snapping.

## Required Structure

1. **Title Slide**
   - Deck title (what this deck argues, not the team's name)
   - Presenter / team line
   - One-line subtitle stating the occasion or audience

2. **Agenda / Thesis Slide**
   - Either a 3-5 item agenda, or a single thesis sentence that the rest of
     the deck defends. Pick one, not both.

3. **Beat Slides (the body — 3 to 6 of them)**
   - Each slide carries exactly **one idea**
   - Slide title is an **assertion**, not a noun phrase. The audience should
     be able to read titles alone and reconstruct the argument.
   - Supporting visual: a short list, a stat block, or a comparison table.
     Not paragraphs.
   - Slides that make a claim need **evidence** on the same slide (number,
     chart, quote). Never split claim and evidence across two slides.

4. **Closer Slide**
   - The takeaway restated as a call to action
   - Contact / next step

## Beat Discipline

- Structure the body as a **sequence of beats**, each one advancing the
  argument: context -> tension -> resolution -> proof -> ask.
- One idea per slide. If a slide needs two titles, split it.
- 8-15 slides is the normal range for a business or product deck.
- Slide titles must read as a coherent argument when skimmed in order.

## Design Requirements

- Full-viewport slides; scroll-snap for slide-at-a-time navigation
- Large type sized for projection (title >= 2.5rem, body >= 1.25rem)
- High contrast — projected decks wash out, so avoid low-contrast greys
- One consistent layout grammar; vary emphasis, not structure
- Semantic HTML; keyboard arrow navigation between slides

## Content Guidelines

- Use realistic placeholder content, not lorem ipsum
- Keep body copy to <= 5 bullets or <= 40 words per slide
- Mark any missing metric as `[NEEDS DATA]` rather than inventing a number
- Prefer charts/tables over bullet lists for comparative claims