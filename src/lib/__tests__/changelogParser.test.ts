import { describe, expect, it } from 'vitest';

import {
  parseChangelog,
  formatChangelogAuditSummary,
  formatChangelogAuditJson,
} from '../changelogParser';

describe('changelogParser audit helpers', () => {
  it('parses markdown and formats changelog audit summary and json', () => {
    const md = `## [v1.2.0] - 2026-10-10
### Added
- New project workbench
### Fixed
- Fixed header layout
`;
    const entries = parseChangelog(md);
    expect(formatChangelogAuditSummary(entries)).toBe(
      'versions=1 · latest=v1.2.0 · major=1 · improvements=0 · fixes=1',
    );
    const parsed = JSON.parse(formatChangelogAuditJson(entries));
    expect(parsed).toEqual({
      versionCount: 1,
      latestVersion: 'v1.2.0',
      latestDate: '2026-10-10',
      majorCount: 1,
      improvementCount: 0,
      fixCount: 1,
    });
  });

  it('handles empty or nullish entries safely', () => {
    expect(formatChangelogAuditSummary(null)).toBe(
      'versions=0 · latest=none · major=0 · improvements=0 · fixes=0',
    );
    expect(JSON.parse(formatChangelogAuditJson([])).latestVersion).toBeNull();
  });
});
