import { describe, expect, it } from 'vitest';

import { auditBackendRequestGovernance } from '../backendRequest';

describe('auditBackendRequestGovernance (P174)', () => {
  it('returns compliant governance audit metadata for backendRequest', () => {
    const report = auditBackendRequestGovernance();
    expect(report.module).toBe('src/shared/api/backendRequest.ts');
    expect(report.phase).toBe('P174');
    expect(report.domain).toBe('shared-api');
    expect(report.failClosedFallbackErrorCode).toBe('BACKEND_NOT_AVAILABLE');
    expect(report.compliant).toBe(true);
  });
});
