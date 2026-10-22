import { describe, expect, it } from 'vitest';

import { evaluateHelpAboutTabGovernanceAudit } from '../AboutTab';

describe('evaluateHelpAboutTabGovernanceAudit (Phase P141)', () => {
  it('returns healthy report for valid app version, electron version, and license disclosure', () => {
    const report = evaluateHelpAboutTabGovernanceAudit({
      appVersion: '0.9.4',
      electronVersion: '33.2.0',
      hasLicenseDisclosure: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.hasValidSemverPrefix).toBe(true);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags invalid version, empty electron version, and missing license disclosure', () => {
    const report = evaluateHelpAboutTabGovernanceAudit({
      appVersion: 'invalid',
      electronVersion: '   ',
      hasLicenseDisclosure: false,
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'HELP_ABOUT_VERSION_INVALID',
      'HELP_ABOUT_ELECTRON_VERSION_EMPTY',
      'HELP_ABOUT_LICENSE_DISCLOSURE_MISSING',
    ]);
  });
});
