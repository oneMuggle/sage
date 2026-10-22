import { describe, expect, it } from 'vitest';

import { auditSessionWorkspaceProviderGovernance } from '../SessionWorkspaceProvider';

describe('SessionWorkspaceProvider P151 governance audit', () => {
  it('returns healthy defaults for SessionWorkspaceProvider governance', () => {
    const res = auditSessionWorkspaceProviderGovernance();
    expect(res.module).toBe('src/app/providers/SessionWorkspaceProvider.tsx');
    expect(res.phase).toBe('P151');
    expect(res.status).toBe('ready');
    expect(res.hasActiveSession).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when status is error', () => {
    const res = auditSessionWorkspaceProviderGovernance({
      status: 'error',
      hasActiveSession: false,
    });
    expect(res.status).toBe('error');
    expect(res.hasActiveSession).toBe(false);
    expect(res.healthy).toBe(false);
  });
});
