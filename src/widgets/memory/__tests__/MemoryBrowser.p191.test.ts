import { describe, expect, it } from 'vitest';

import { auditMemoryBrowserGovernance } from '../MemoryBrowser';

describe('auditMemoryBrowserGovernance (Phase P191)', () => {
  it('returns deterministic P191 governance audit payload', () => {
    const payload = JSON.parse(auditMemoryBrowserGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('memory-browser');
    expect(payload.phase).toBe('P191');
    expect(payload.audited).toBe(true);
  });
});
