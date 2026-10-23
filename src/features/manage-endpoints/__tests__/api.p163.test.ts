import { describe, expect, it } from 'vitest';

import {
  auditManageEndpointsApiGovernance,
  formatProbeResultJson,
  formatProbeResultSummary,
} from '../api';

describe('manage-endpoints api governance audit (P163)', () => {
  it('returns ready governance status for manage-endpoints/api.ts', () => {
    const snap = auditManageEndpointsApiGovernance();
    expect(snap).toEqual({
      moduleId: 'src/features/manage-endpoints/api.ts',
      phase: 'P163',
      status: 'ready',
    });
  });

  it('formats probe result summary and json', () => {
    const res = {
      status: 'unsupported' as const,
      adapter: 'unknown',
      data: null,
      error: 'demo',
    };
    expect(formatProbeResultSummary(res)).toContain('unsupported · unknown · demo');
    expect(JSON.parse(formatProbeResultJson(res))).toMatchObject({
      status: 'unsupported',
      adapter: 'unknown',
      error: 'demo',
    });
  });
});
