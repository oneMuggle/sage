import { describe, expect, it } from 'vitest';

import { auditChangelogParserGovernance } from '../changelogParser';

describe('auditChangelogParserGovernance (P170)', () => {
  it('returns compliant governance audit metadata for changelogParser', () => {
    const report = auditChangelogParserGovernance();
    expect(report.module).toBe('src/lib/changelogParser.ts');
    expect(report.phase).toBe('P170');
    expect(report.domain).toBe('lib');
    expect(report.highlightCategories).toEqual(['major', 'improvements', 'fixes']);
    expect(report.compliant).toBe(true);
  });
});
