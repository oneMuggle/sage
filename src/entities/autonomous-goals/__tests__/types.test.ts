import { describe, expect, it } from 'vitest';

import { formatGoalAuditJson, formatGoalAuditSummary } from '../types';

describe('autonomous-goals types audit helpers', () => {
  it('formats goal audit summary and JSON (Phase P120)', () => {
    const sample = {
      id: 'g-10',
      name: 'Nightly index',
      status: 'running' as const,
      completion_percentage: 75,
      degradation_level: 'none' as const,
      checkpoints: [
        {
          id: 'c1',
          type: 'command' as const,
          description: 'build',
          file_path: null,
          verification_command: 'npm test',
          expected_pattern: null,
          verified: true,
        },
      ],
    };
    expect(formatGoalAuditSummary(sample)).toBe(
      'g-10 · status=running · progress=75% · checkpoints=1/1 · deg=none',
    );
    expect(JSON.parse(formatGoalAuditJson(sample))).toEqual({
      id: 'g-10',
      name: 'Nightly index',
      status: 'running',
      completionPercentage: 75,
      verifiedCheckpoints: 1,
      totalCheckpoints: 1,
      degradationLevel: 'none',
    });
  });
});
