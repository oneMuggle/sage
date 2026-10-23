import { describe, expect, it } from 'vitest';

import { auditUseWikiIngestGovernance } from '../useWikiIngest';

describe('auditUseWikiIngestGovernance (P170)', () => {
  it('returns compliant governance audit metadata for useWikiIngest', () => {
    const report = auditUseWikiIngestGovernance();
    expect(report.module).toBe('src/features/wiki/useWikiIngest.ts');
    expect(report.phase).toBe('P170');
    expect(report.domain).toBe('wiki');
    expect(report.multiplexesListenersByIngestId).toBe(true);
    expect(report.supportsReset).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
