import { describe, expect, it } from 'vitest';

import { evaluateWikiFileTreeGovernanceAudit } from '../WikiFileTree';

describe('evaluateWikiFileTreeGovernanceAudit (Phase P140)', () => {
  it('returns healthy report for valid wiki file tree state', () => {
    const report = evaluateWikiFileTreeGovernanceAudit({
      pageCount: 24,
      selectedPagePath: 'concepts/architecture.md',
      expandedFolderPaths: ['concepts', 'guides'],
    });
    expect(report.healthy).toBe(true);
    expect(report.normalizedPageCount).toBe(24);
    expect(report.uniqueExpandedFolderCount).toBe(2);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags negative page count and path traversal in selected page path', () => {
    const report = evaluateWikiFileTreeGovernanceAudit({
      pageCount: -4,
      selectedPagePath: '../secret.md',
      expandedFolderPaths: [],
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'WIKI_FILE_TREE_PAGE_COUNT_NEGATIVE',
      'WIKI_FILE_TREE_SELECTED_PATH_TRAVERSAL',
    ]);
  });
});
