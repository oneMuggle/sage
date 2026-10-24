import { describe, expect, it } from 'vitest';

import { auditPluginClientGovernance } from '../pluginClient';

describe('auditPluginClientGovernance (Phase P189)', () => {
  it('returns deterministic P189 governance audit payload', () => {
    const payload = JSON.parse(auditPluginClientGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('plugin-client');
    expect(payload.phase).toBe('P189');
    expect(payload.audited).toBe(true);
  });
});
