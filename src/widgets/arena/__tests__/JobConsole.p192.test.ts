import { describe, expect, it } from 'vitest';

import { auditJobConsoleGovernance } from '../JobConsole';

describe('auditJobConsoleGovernance (Phase P192)', () => {
  it('returns deterministic P192 governance audit payload', () => {
    const payload = JSON.parse(auditJobConsoleGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('job-console');
    expect(payload.phase).toBe('P192');
    expect(payload.audited).toBe(true);
  });
});
