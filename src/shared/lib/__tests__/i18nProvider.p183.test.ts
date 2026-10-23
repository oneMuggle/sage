import { describe, expect, it } from 'vitest';

import { auditI18nProviderGovernance } from '../i18n/index';

describe('auditI18nProviderGovernance (Phase P183)', () => {
  it('returns deterministic P183 governance audit payload', () => {
    const payload = JSON.parse(auditI18nProviderGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('i18n-provider');
    expect(payload.phase).toBe('P183');
    expect(payload.audited).toBe(true);
  });
});
