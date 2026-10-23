import { describe, expect, it } from 'vitest';

import { auditThinkingPlaceholderGovernance } from '../thinkingPlaceholder';

describe('auditThinkingPlaceholderGovernance (P168)', () => {
  it('returns compliant governance audit metadata for thinkingPlaceholder', () => {
    const report = auditThinkingPlaceholderGovernance();
    expect(report.module).toBe('src/features/send-message/thinkingPlaceholder.ts');
    expect(report.phase).toBe('P168');
    expect(report.domain).toBe('send-message');
    expect(report.sentinelDefined).toBe(true);
    expect(report.rendersShimmerBeforeFirstToken).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
