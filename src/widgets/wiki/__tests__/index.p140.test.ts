import { describe, expect, it } from 'vitest';

import { evaluateWikiBarrelGovernanceAudit } from '../index';

describe('evaluateWikiBarrelGovernanceAudit (Phase P140)', () => {
  it('returns healthy report when wiki barrel exports all core wiki widgets', () => {
    const report = evaluateWikiBarrelGovernanceAudit({
      exportedComponentNames: [
        'WikiChat',
        'WikiEditor',
        'WikiFileTree',
        'WikiGraphView',
        'WikiInsightsPanel',
        'WikiQueuePanel',
        'WikiLintView',
        'WikiReviewView',
        'WikiResearchPanel',
        'WikiSearch',
      ],
      hasWikiEditorExport: true,
      hasWikiGraphViewExport: true,
      hasWikiSearchExport: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.uniqueExportCount).toBe(10);
    expect(report.completeCoreWikiExports).toBe(true);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags incomplete wiki barrel exports', () => {
    const report = evaluateWikiBarrelGovernanceAudit({
      exportedComponentNames: ['WikiEditor'],
      hasWikiEditorExport: true,
      hasWikiGraphViewExport: false,
      hasWikiSearchExport: false,
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'WIKI_BARREL_EXPORTS_INCOMPLETE',
      'WIKI_CORE_EXPORT_MISSING',
    ]);
  });
});
