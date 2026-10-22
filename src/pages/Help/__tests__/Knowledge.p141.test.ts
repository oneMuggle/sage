import { describe, expect, it } from 'vitest';

import { evaluateKnowledgePageGovernanceAudit } from '../../Knowledge';

describe('evaluateKnowledgePageGovernanceAudit (Phase P141)', () => {
  it('returns healthy report for active project and supported knowledge page view mode', () => {
    const report = evaluateKnowledgePageGovernanceAudit({
      activeProjectId: 'proj-alpha',
      activeViewMode: 'editor',
      allowedViewModes: ['editor', 'graph', 'sources', 'lint', 'review'],
      isWikiReady: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.normalizedProjectId).toBe('proj-alpha');
    expect(report.viewModeSupported).toBe(true);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags empty project ID, unsupported view mode, and unready wiki state', () => {
    const report = evaluateKnowledgePageGovernanceAudit({
      activeProjectId: '   ',
      activeViewMode: 'unknown',
      allowedViewModes: ['editor', 'graph'],
      isWikiReady: false,
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'KNOWLEDGE_PAGE_PROJECT_ID_EMPTY',
      'KNOWLEDGE_PAGE_VIEW_MODE_UNSUPPORTED',
      'KNOWLEDGE_PAGE_WIKI_NOT_READY',
    ]);
  });
});
