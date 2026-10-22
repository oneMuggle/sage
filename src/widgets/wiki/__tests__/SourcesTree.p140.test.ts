import { describe, expect, it } from 'vitest';

import { evaluateWikiSourcesTreeGovernanceAudit } from '../SourcesTree';

describe('evaluateWikiSourcesTreeGovernanceAudit (Phase P140)', () => {
  it('returns healthy report for valid wiki sources tree counts and handlers', () => {
    const report = evaluateWikiSourcesTreeGovernanceAudit({
      rootNodeCount: 3,
      totalSourceFileCount: 14,
      hasFileClickHandler: true,
      hasIngestHandler: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.interactiveReady).toBe(true);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags orphan files and missing interaction handlers', () => {
    const report = evaluateWikiSourcesTreeGovernanceAudit({
      rootNodeCount: 0,
      totalSourceFileCount: 5,
      hasFileClickHandler: false,
      hasIngestHandler: false,
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'WIKI_SOURCES_TREE_ORPHAN_FILES',
      'WIKI_SOURCES_TREE_HANDLERS_INCOMPLETE',
    ]);
  });
});
