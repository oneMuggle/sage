---
name: pricing
kind: prototype
description: "A pricing page with plan comparison table, feature matrix, FAQ accordion, and CTA sections."
design_system_required: true
---

# Pricing Page Template

Generate a pricing page prototype that guides visitors from positioning, through plan and feature comparison, to a confident purchase decision.

## Required Sections

1. **Hero**
   - Headline stating the value proposition (benefit-focused, not feature-focused)
   - Subtitle clarifying who the product is for and what pricing model to expect
   - Optional billing-period toggle (monthly / annual)

2. **Plan Cards**
   - Exactly 3 tiers: Free, Pro, Enterprise
   - Each card: plan name, price, billing cadence, 4-6 key features, and a CTA button
   - The middle tier (Pro) is visually highlighted and recommended
   - Annual price may be shown alongside monthly with a savings note

3. **Feature Comparison Table**
   - Matrix of rows (features or categories) against the 3 plan columns
   - Checkmark for included features, dash for excluded
   - Group rows by category when the feature list is long
   - Header row repeats plan names and prices for scannability

4. **FAQ Section**
   - 5-8 questions with expandable answers
   - Use native `<details>` / `<summary>` or an equivalent accessible disclosure pattern
   - Questions should address real objections: billing, cancellation, limits, security, support

5. **Bottom CTA**
   - Compelling headline that resolves the page's main objection
   - Supporting line and a single prominent action button
   - Visually distinct from surrounding sections (contrasting background or band)

## Design Requirements

- Highlighted tier must be visually distinct via a stronger border, elevated card, or tinted background — and labeled (e.g. "Most popular")
- Use checkmarks for included features and dashes for excluded; keep the two states clearly distinguishable in both light and dark themes
- Feature comparison table: sticky header row on desktop, horizontal scroll or stacked layout on small screens
- Plan cards stack vertically on mobile; grid on tablet and desktop
- Consistent button hierarchy: one primary CTA per plan, with the highlighted tier's CTA strongest
- Accessible color contrast (WCAG AA) and keyboard-operable FAQ disclosures

## Content Guidelines

- Use realistic plan names, feature names, and limits (e.g. "10 GB storage", "Up to 5 seats") — never lorem ipsum
- Format prices in local currency with the correct symbol, grouping, and period (e.g. `¥99 / 月`, `$29 / mo`)
- Keep feature descriptions parallel in grammar and length across tiers
- Make the free-to-paid and paid-to-enterprise upgrade boundaries obvious
