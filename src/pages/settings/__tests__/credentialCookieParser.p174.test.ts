import { describe, expect, it } from 'vitest';

import { auditCredentialCookieParserGovernance } from '../credentialCookieParser';

describe('auditCredentialCookieParserGovernance (P174)', () => {
  it('returns compliant governance audit metadata for credentialCookieParser', () => {
    const report = auditCredentialCookieParserGovernance();
    expect(report.module).toBe('src/pages/settings/credentialCookieParser.ts');
    expect(report.phase).toBe('P174');
    expect(report.domain).toBe('settings');
    expect(report.sampleCookieCount).toBe(2);
    expect(report.compliant).toBe(true);
  });
});
