---
name: dashboard
kind: prototype
description: "A data dashboard with KPI cards, charts, activity feed, and data table. Optimized for the data-report design system."
design_system_required: true
---

# Dashboard Template

Generate a data dashboard prototype that reads as a single operational view: headline metrics up top, trend visualization in the middle, and recent activity plus tabular detail below.

## Required Sections

1. **Top Navigation**
   - Product or workspace title on the left
   - User avatar (and optional account menu) on the right
   - Persistent across scroll (sticky); subtle bottom border or shadow to separate from content

2. **KPI Row**
   - Exactly 4 metric cards
   - Each card: metric label, large primary value, period-over-period delta (with direction arrow and sign), and a small sparkline
   - Sparkline can be an inline SVG or CSS-only mini bar/line — no chart library required

3. **Main Chart Area**
   - One primary visualization: line chart (trend over time) or bar chart (comparison by category)
   - Title, timeframe selector (e.g. 7d / 30d / 90d), and legend
   - Render the chart with CSS (flex/grid bars or an inline SVG path) so the prototype has no external dependencies
   - Include axis labels and a readable value scale

4. **Activity Feed**
   - 5-8 recent items, newest first
   - Each item: relative timestamp, short description, and (optionally) actor name or icon
   - Visually separate items with dividers or alternating subtle backgrounds

5. **Data Table**
   - 8-12 rows of realistic records
   - Sortable column headers (show sort affordance on the active column)
   - Columns appropriate to the domain: name/entity, status, numeric value, date
   - Include a status badge style for categorical values

## Design Requirements

- Use `font-variant-numeric: tabular-nums` on all numeric values (KPI values, deltas, table numbers, axis labels) so digits align
- Deltas: green for positive, red for negative, neutral gray for flat; show explicit `+` / `-` and unit
- Responsive grid: 4 columns on desktop, 2 columns on tablet, 1 column on mobile for KPI cards and major panels
- Sticky top navigation that stays visible while the content scrolls
- Consistent card padding, corner radius, and elevation across all panels
- Accessible color contrast (WCAG AA); never rely on color alone to convey delta direction

## Content Guidelines

- Use realistic business metrics (e.g. "Monthly Recurring Revenue", "Active Sessions", "Conversion Rate") — never lorem ipsum
- Numbers should be plausible and internally consistent (e.g. delta percentages that match the sparkline direction)
- When a value is unavailable, mark it explicitly as `[NEEDS DATA]` rather than inventing a placeholder
- Keep labels short and scannable; put units in the label or as a suffix, not buried in prose
