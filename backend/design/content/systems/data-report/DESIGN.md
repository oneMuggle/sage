# Data Report Design System

A data-dense design system optimized for reports, dashboards, and analytics. Table-first, chart-friendly, high information density.

## Visual Theme

**Mood**: Precise, trustworthy, information-dense

**Inspiration**:
- Bloomberg Terminal: Dense, professional, data-centric
- Stripe Reports: Clean layouts, excellent typography for numbers
- Observable Notebooks: Interactive data exploration, clarity first

**Core Principles**:
- Data is the hero, not decoration
- Every pixel should serve information
- Numbers must be scannable and comparable
- Color communicates meaning, not just aesthetics

## Color Palette

### Background Colors

```css
/* Primary backgrounds */
--dr-bg-primary: #ffffff;           /* Main content area */
--dr-bg-secondary: #f8fafc;         /* Card backgrounds, alternating rows */
--dr-bg-tertiary: #f1f5f9;          /* Hover states, selected rows */
--dr-bg-muted: #e2e8f0;             /* Disabled states, borders */
```

### Text Colors

```css
/* Text hierarchy */
--dr-fg-primary: #0f172a;           /* Headings, primary values */
--dr-fg-secondary: #475569;         /* Labels, descriptions */
--dr-fg-tertiary: #64748b;          /* Metadata, timestamps */
--dr-fg-muted: #94a3b8;             /* Disabled text, placeholders */
```

### Categorical Colors (Chart Series)

8 distinct hues optimized for data visualization, tested for distinguishability:

```css
/* Categorical palette for charts and series */
--dr-cat-blue: #2563eb;             /* Primary series, most prominent */
--dr-cat-teal: #0d9488;             /* Secondary series */
--dr-cat-amber: #d97706;            /* Tertiary series */
--dr-cat-rose: #e11d48;             /* Quaternary series */
--dr-cat-violet: #7c3aed;           /* Fifth series */
--dr-cat-emerald: #059669;          /* Sixth series */
--dr-cat-orange: #ea580c;           /* Seventh series */
--dr-cat-slate: #475569;            /* Eighth series, neutral */
```

**Usage Guidelines**:
- Use in order for consistent series identification
- Maximum 8 categorical colors to avoid confusion
- Blue (#2563eb) should be the default/primary series color
- Ensure sufficient contrast on both light and dark backgrounds

### Semantic Colors

Colors that communicate meaning through association:

```css
/* Semantic data colors */
--dr-semantic-up: #059669;          /* Positive values, growth, success */
--dr-semantic-down: #dc2626;        /* Negative values, decline, error */
--dr-semantic-neutral: #64748b;     /* No change, baseline */
--dr-semantic-warning: #d97706;     /* Attention needed */
--dr-semantic-info: #2563eb;        /* Informational, neutral data */
```

**Usage Rules**:
- Green = positive direction (up, growth, profit)
- Red = negative direction (down, loss, error)
- Gray = neutral, no change, baseline
- Never use red/green for non-directional data (use categorical palette instead)

## Typography

### Font Families

```css
/* Font stacks */
--dr-font-ui: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
--dr-font-mono: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
```

**Inter**: Used for all UI text, labels, descriptions
**Monospace**: Used for data values, numbers, codes, identifiers

### Typography Scale

Compact scale optimized for data density (13px-16px range):

```css
/* Typography scale */
--dr-text-xs: 11px;                 /* Metadata, timestamps, footnotes */
--dr-text-sm: 13px;                 /* Table cells, secondary data */
--dr-text-base: 14px;               /* Default body text, labels */
--dr-text-md: 15px;                 /* Emphasized text, subheadings */
--dr-text-lg: 16px;                 /* Section headings, KPI values */
--dr-text-xl: 18px;                 /* Page titles, major KPIs */
--dr-text-2xl: 24px;                /* Hero metrics (rare, use sparingly) */
```

### Tabular Numerals

**CRITICAL**: All numbers must use tabular numerals for vertical alignment:

```css
/* Apply to all data values, table cells, charts */
font-variant-numeric: tabular-nums;
```

**Why**: Tabular numerals ensure all digits have equal width, so columns of numbers align perfectly. This is essential for:
- Financial data (prices, amounts)
- Metrics and KPIs
- Table cells with numeric data
- Chart axis labels
- Any data that needs vertical comparison

### Font Weights

```css
--dr-font-regular: 400;             /* Body text, descriptions */
--dr-font-medium: 500;              /* Labels, emphasized text */
--dr-font-semibold: 600;            /* Headings, KPI values */
--dr-font-bold: 700;                /* Hero metrics (use sparingly) */
```

## Spacing

### Base Grid

4px grid system for tight data layouts:

```css
/* Spacing scale (4px grid) */
--dr-space-1: 4px;                  /* Tight spacing, icon gaps */
--dr-space-2: 8px;                  /* Cell padding, small gaps */
--dr-space-3: 12px;                 /* Component internal spacing */
--dr-space-4: 16px;                 /* Card padding, standard gaps */
--dr-space-5: 20px;                 /* Section spacing */
--dr-space-6: 24px;                 /* Large section spacing */
--dr-space-8: 32px;                 /* Page margins, major sections */
```

### Component Spacing

**Tables**:
- Cell padding: 8px horizontal, 6px vertical
- Row height: 32px minimum (40px for comfortable reading)
- Header height: 36px

**Cards**:
- Padding: 16px (standard), 12px (compact)
- Gap between cards: 16px

**Charts**:
- Container padding: 16px all sides
- Chart area padding: 8px (for axis labels)

## Component Stylings

### Tables

**Visual Design**:
- Zebra striping: Alternate rows use --dr-bg-secondary
- Hover highlight: Hovered row uses --dr-bg-tertiary
- Borders: 1px solid --dr-bg-muted for row dividers
- Header: Slightly darker background (--dr-bg-tertiary), bold text

**Data Alignment**:
- Text: Left-aligned
- Numbers: Right-aligned (critical for comparison)
- Dates: Right-aligned or centered
- Actions: Right-aligned

**Sortable Headers**:
- Cursor: pointer on hover
- Sort indicator: Small arrow icon (up/down/neutral)
- Active sort: Bold text, colored indicator

**Sticky Headers**:
- Position: sticky, top: 0
- Background: --dr-bg-tertiary with 98% opacity (for scroll indication)
- Box-shadow: 0 1px 2px rgba(0,0,0,0.05) when scrolled

### KPI Cards

**Structure**:
- Large number (primary metric): 24px-32px, semibold, tabular-nums
- Label: 13px, --dr-fg-secondary
- Delta/trend: 14px, colored arrow + percentage (green up, red down)
- Optional sparkline: 60px wide, inline with delta

**Layout**:
- Padding: 16px
- Background: --dr-bg-primary or --dr-bg-secondary
- Border: 1px solid --dr-bg-muted or border-radius: 6px with subtle shadow

### Chart Containers

**Consistent Padding**:
- All sides: 16px
- Title area: 8px bottom margin
- Legend: 12px top margin (if below chart)

**Chart Area**:
- Background: --dr-bg-primary
- Grid lines: 1px solid --dr-bg-muted, dashed for minor grid
- Axis labels: 12px, --dr-fg-tertiary
- Data points: 4px-6px diameter, categorical colors

**Tooltips**:
- Background: --dr-bg-primary with box-shadow
- Border: 1px solid --dr-bg-muted
- Padding: 8px
- Font: 13px, tabular-nums for values

### Sparklines

**Inline with Text**:
- Height: 16px-20px (match line height)
- Width: 60px-80px
- Stroke: 1.5px, categorical color
- No fill (line only)
- Align: middle with text

**Standalone**:
- Height: 40px-60px
- Width: 100% of container
- Can include area fill (10% opacity of stroke color)

### Data Grids

**Cell Styling**:
- Padding: 8px horizontal, 6px vertical
- Border-bottom: 1px solid --dr-bg-muted
- Hover: background --dr-bg-tertiary

**Header Cells**:
- Background: --dr-bg-tertiary
- Font-weight: 600 (semibold)
- Cursor: pointer (if sortable)
- Sort indicator: Right-aligned arrow icon

**Selection**:
- Selected row: background --dr-bg-tertiary, left border 2px solid --dr-cat-blue
- Checkbox column: 32px wide, centered

## Layout

### Dashboard Layout

**Full-Width**:
- Max-width: 1400px (centered with margin: 0 auto)
- Padding: 24px horizontal

**Grid System**:
- Columns: 12-column grid
- Gap: 16px
- Responsive breakpoints: 768px (tablet), 1024px (desktop), 1400px (large)

**Common Layouts**:
- KPI row: 3-4 cards in a row (equal width)
- Chart + table: 6+6 columns or 4+8 columns
- Multi-panel: 2x2 grid for 4 equal panels
- Sidebar + main: 240px sidebar + fluid main area

### Scrollable Tables

**Sticky Headers**:
- Position: sticky, top: 0
- Z-index: 10 (above data rows)
- Background: --dr-bg-tertiary with 98% opacity

**Sticky Columns** (optional):
- First column: position sticky, left: 0
- Background: inherit (must match row background)
- Box-shadow: 2px 0 4px rgba(0,0,0,0.05) when scrolled

**Virtual Scrolling**:
- For tables > 100 rows, use virtual scrolling
- Row height: fixed (32px or 40px)
- Buffer: 5 rows above and below viewport

## Do's

### Always Do

1. **Use tabular numerals everywhere**: `font-variant-numeric: tabular-nums` on all data values
2. **Right-align numbers**: All numeric data should be right-aligned for easy comparison
3. **Consistent decimal places**: Same number of decimals in a column (e.g., all prices to 2 decimals)
4. **Use color semantically**: Green = up/positive, red = down/negative, gray = neutral
5. **Use sparklines for trends**: Show historical context inline with current values
6. **Use small multiples**: For comparing similar metrics across categories
7. **Provide context**: Always show units, deltas, and benchmarks where relevant
8. **Optimize for scanning**: Use consistent alignment, spacing, and visual hierarchy
9. **Make data actionable**: Highlight outliers, thresholds, and recommended actions
10. **Test with real data**: Ensure layouts work with both small and large numbers

## Don'ts

### Never Do

1. **No decorative charts**: Avoid 3D pie charts, unnecessary gradients, or decorative elements
2. **No mixed number formats**: Don't mix percentages and absolutes in same column
3. **No more than 8 categorical colors**: Beyond 8, users can't distinguish series
4. **No text-heavy paragraphs**: Data views should be scannable, not read like prose
5. **No large hero sections**: Data IS the hero, not marketing copy
6. **No rainbow color schemes**: Use the categorical palette, not arbitrary colors
7. **No left-aligned numbers**: Makes vertical comparison impossible
8. **No proportional fonts for data**: Always use tabular-nums or monospace
9. **No unnecessary chart junk**: Remove grid lines, legends, labels that don't add information
10. **No misleading scales**: Always start y-axis at 0 for bar charts, be explicit for line charts

## Accessibility

### Color Contrast

- Text on background: Minimum 4.5:1 contrast ratio (WCAG AA)
- Large text (18px+): Minimum 3:1 contrast ratio
- Chart colors: Test for color blindness (deuteranopia, protanopia)

### Keyboard Navigation

- All interactive elements (sortable headers, filters) must be keyboard accessible
- Focus indicators: 2px solid outline, --dr-cat-blue color
- Tab order: Logical left-to-right, top-to-bottom

### Screen Readers

- Use semantic HTML (<table>, <th>, <td>)
- aria-label for charts and visualizations
- aria-sort for sortable columns
- Announce dynamic data updates with aria-live

## Performance

### Rendering

- Use CSS transforms for animations (not layout properties)
- Virtualize long lists and tables (>100 rows)
- Lazy-load charts below the fold

### Data Loading

- Show loading skeletons, not spinners (maintains layout)
- Progressive loading: Show data as it arrives
- Cache frequently accessed data

## Examples

### KPI Card

```html
<div class="kpi-card">
  <div class="kpi-label">Monthly Revenue</div>
  <div class="kpi-value">$1,234,567</div>
  <div class="kpi-delta positive">
    <span class="kpi-arrow">&#8593;</span>
    <span class="kpi-change">+12.5%</span>
    <span class="kpi-sparkline"><!-- sparkline SVG --></span>
  </div>
</div>
```

### Data Table

```html
<table class="data-table">
  <thead>
    <tr>
      <th class="sortable">Product</th>
      <th class="sortable numeric">Units Sold</th>
      <th class="sortable numeric">Revenue</th>
      <th class="sortable numeric">Growth</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>Product A</td>
      <td class="numeric">1,234</td>
      <td class="numeric">$45,678</td>
      <td class="numeric positive">+12.5%</td>
    </tr>
  </tbody>
</table>
```

## References

- **Design Inspiration**: Bloomberg Terminal, Stripe Reports, Observable
- **Typography**: Inter (UI), JetBrains Mono (data)
- **Color Theory**: categorical palette tested for distinguishability
- **Best Practices**: Edward Tufte's data-ink ratio, Stephen Few's dashboard design principles
