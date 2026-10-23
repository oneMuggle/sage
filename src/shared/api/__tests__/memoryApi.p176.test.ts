import { describe, expect, it } from 'vitest';

import {
  auditMemoryApiGovernance,
  formatMemoryListJson,
  formatMemoryListSummary,
} from '../memoryApi';

describe('memoryApi P176 governance audit', () => {
  it('audits memoryApi governance contract and memory list formatters', () => {
    const raw = auditMemoryApiGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.api.memory_api.governance.v1');
    expect(parsed.phase).toBe('P176');
    expect(parsed.supportedLayers).toContain('episodic');
    const sample = {
      items: [],
      total: 0,
      page: 1,
      page_size: 20,
      layer: 'all' as const,
      source_breakdown: { working: 0, session_summary: 0, episodic: 0, semantic: 0 },
    };
    expect(formatMemoryListSummary(sample)).toBe('all · 0/0 items · page 1');
    expect(JSON.parse(formatMemoryListJson(sample)).total).toBe(0);
  });
});
