import { describe, expect, it } from 'vitest';

import { auditFileSearchClientGovernance } from '../fileSearchClient';

describe('auditFileSearchClientGovernance (P175)', () => {
  it('returns compliant governance audit metadata for fileSearchClient', () => {
    const report = auditFileSearchClientGovernance();
    expect(report.module).toBe('src/shared/api/fileSearchClient.ts');
    expect(report.phase).toBe('P175');
    expect(report.domain).toBe('shared-api');
    expect(report.supportsOfficeAndWorkspaceFileClassification).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
