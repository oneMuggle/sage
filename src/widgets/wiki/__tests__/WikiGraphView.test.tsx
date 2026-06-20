/**
 * WikiGraphView helpers tests
 *
 * Exercises the @internal exports `colorByType` and `buildGraph` from
 * WikiGraphView.tsx. The test file lives in `__tests__/` rather than at the
 * top level of WikiGraphView.tsx so that Vite's dep optimizer does not
 * execute vitest's `describe()` in the browser dev server (which throws
 * "Cannot read properties of undefined (reading 'config')" because vitest's
 * test runner config is not present in the browser context).
 */
import { describe, it, expect } from 'vitest';

import type { GraphData } from '../../../shared/types/wiki';
import { buildGraph, colorByType } from '../WikiGraphView';

// ============================================================================
// colorByType
// ============================================================================

describe('colorByType', () => {
  it('returns default color for undefined pageType', () => {
    expect(colorByType(undefined)).toBe('#94a3b8');
  });

  it('returns default color for unknown pageType', () => {
    expect(colorByType('unknown_type')).toBe('#94a3b8');
  });

  it('returns mapped color for known pageType', () => {
    expect(colorByType('source')).toBe('#3b82f6');
    expect(colorByType('entity')).toBe('#8b5cf6');
  });
});

// ============================================================================
// buildGraph
// ============================================================================

describe('buildGraph', () => {
  const sampleData: GraphData = {
    nodes: [
      {
        id: 'a',
        label: 'A',
        page_type: 'source',
        sources: ['x.pdf'],
        wikilinks: [],
      },
      {
        id: 'b',
        label: 'B',
        page_type: 'concept',
        sources: [],
        wikilinks: [],
      },
    ],
    edges: [{ source: 'a', target: 'b', signal: 'DirectLink', weight: 3.0 }],
  };

  it('produces nodes and edges from GraphData', () => {
    const { nodes, edges } = buildGraph(sampleData);
    expect(nodes).toHaveLength(2);
    expect(edges).toHaveLength(1);
    expect(nodes[0].data.highlighted).toBe(true);
  });

  it('dims non-matching nodes when query set', () => {
    const data: GraphData = {
      nodes: [
        { id: 'a', label: 'Albert', page_type: 'entity', sources: [], wikilinks: [] },
        { id: 'b', label: 'Other', page_type: 'entity', sources: [], wikilinks: [] },
      ],
      edges: [],
    };
    const { nodes, matchedIds } = buildGraph(data, 'albert');
    expect(matchedIds.has('a')).toBe(true);
    expect(matchedIds.has('b')).toBe(false);
    expect(nodes[0].data.highlighted).toBe(true);
    expect(nodes[1].data.highlighted).toBe(false);
  });

  it('matches case-insensitively by label', () => {
    const data: GraphData = {
      nodes: [{ id: 'a', label: 'ALBERT', page_type: 'entity', sources: [], wikilinks: [] }],
      edges: [],
    };
    const { matchedIds } = buildGraph(data, 'albert');
    expect(matchedIds.has('a')).toBe(true);
  });

  it('matches by id (file path)', () => {
    const data: GraphData = {
      nodes: [{ id: 'wiki/sources/albert.md', label: 'X', sources: [], wikilinks: [] }],
      edges: [],
    };
    const { matchedIds } = buildGraph(data, 'albert');
    expect(matchedIds.has('wiki/sources/albert.md')).toBe(true);
  });

  it('returns empty matchedIds when query is empty/whitespace', () => {
    const { matchedIds } = buildGraph(sampleData, '   ');
    expect(matchedIds.size).toBe(0);
  });
});
