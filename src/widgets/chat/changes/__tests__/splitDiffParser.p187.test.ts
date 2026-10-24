import { describe, expect, it } from 'vitest';

import { auditSplitDiffParserGovernance } from '../splitDiffParser';

describe('auditSplitDiffParserGovernance (Phase P187)', () => {
  it('returns deterministic P187 governance audit payload', () => {
    const payload = JSON.parse(auditSplitDiffParserGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('split-diff-parser');
    expect(payload.phase).toBe('P187');
    expect(payload.audited).toBe(true);
  });
});
