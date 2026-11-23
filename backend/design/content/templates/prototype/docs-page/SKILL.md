---
name: docs-page
kind: prototype
description: "A documentation page with sidebar navigation, search, content area with code blocks, and table of contents."
design_system_required: true
---

# Documentation Page Template

Generate a documentation page prototype optimized for extended reading: persistent navigation on both sides, a comfortable reading column, and rich content primitives for code and callouts.

## Required Sections

1. **Top Navigation**
   - Product logo / name on the left
   - Search bar (with keyboard-shortcut hint such as `⌘K`) in the center or right
   - Theme toggle (light / dark) on the right
   - Sticky at the top of the viewport

2. **Left Sidebar**
   - Hierarchical navigation, 3 levels deep: section > page > anchor
   - Current page and current anchor are both indicated
   - Collapsible groups; the sidebar itself collapses on mobile behind a menu button
   - Sticky and independently scrollable on desktop

3. **Main Content Area**
   - Article heading (h1) plus body copy organized under h2-h4 headings
   - Paragraphs kept to a readable measure (max-width 800px)
   - Code blocks with syntax-highlighting colors and a copy button styled in the block's top-right corner
   - Callout boxes for info, warning, and error states
   - Inline code styling distinct from full code blocks

4. **Right Table of Contents**
   - Auto-generated from h2-h4 headings in the content area
   - Highlights the section currently in view (scroll spy)
   - Clicking an entry smooth-scrolls to the anchor
   - Hidden on narrow viewports where space is insufficient

## Design Requirements

- Reading column max-width 800px, centered between the sidebars
- Sidebar collapsible on mobile (drawer or off-canvas pattern); content remains primary
- Code blocks: monospace font, distinct background, language label where helpful, syntax-highlighting token colors derived from the design system, and a visible copy affordance
- Callout boxes: colored left border (info = neutral/blue, warning = amber, error = red) with matching icon and background tint
- Smooth scroll to anchors with an offset so sticky header does not overlap the target heading
- Proper heading hierarchy (h1 → h2 → h3 → h4); never skip levels
- Accessible color contrast (WCAG AA) in both light and dark themes, including syntax-highlighting tokens

## Content Guidelines

- Use realistic documentation content: installation steps, configuration reference, or API usage — never lorem ipsum
- Distinguish inline code (single identifiers, commands, paths) from code blocks (multi-line examples)
- Keep paragraphs short; use lists and headings to structure scanning
- Callouts should carry actionable guidance, not decoration; match the callout type to the severity of the message
