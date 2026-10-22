import { describe, expect, it } from 'vitest';

import { evaluateHelpChangelogTabGovernanceAudit } from '../ChangelogTab';

describe('evaluateHelpChangelogTabGovernanceAudit (Phase P141)', () => {
  it('returns healthy report for unique changelog release versions with release dates', () => {
    const report = evaluateHelpChangelogTabGovernanceAudit({
      releaseEntryVersions: ['0.9.4', '0.9.3', '0.9.2'],
      hasReleaseDates: true,
      latestEntryHighlighted: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.uniqueReleaseCount).toBe(3);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags duplicate release versions and missing release dates', () => {
    const report = evaluateHelpChangelogTabGovernanceAudit({
      releaseEntryVersions: ['0.9.4', '0.9.4'],
      hasReleaseDates: false,
      latestEntryHighlighted: false,
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'HELP_CHANGELOG_DUPLICATE_VERSION',
      'HELP_CHANGELOG_DATES_MISSING',
    ]);
  });
});
