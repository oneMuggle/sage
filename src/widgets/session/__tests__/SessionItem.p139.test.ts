import { describe, expect, it } from 'vitest';

import { evaluateSessionItemGovernanceAudit } from '../SessionItem';

describe('evaluateSessionItemGovernanceAudit (Phase P139)', () => {
  it('returns healthy report for valid session item metadata', () => {
    const report = evaluateSessionItemGovernanceAudit({
      sessionId: 'sess-2026-1022',
      title: 'Architecture Review',
      messageCount: 18,
      isPinned: true,
      isEditingTitle: false,
    });
    expect(report.healthy).toBe(true);
    expect(report.normalizedSessionId).toBe('sess-2026-1022');
    expect(report.normalizedTitle).toBe('Architecture Review');
    expect(report.normalizedMessageCount).toBe(18);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags empty session ID, empty non-editing title, and negative message count', () => {
    const report = evaluateSessionItemGovernanceAudit({
      sessionId: '   ',
      title: '',
      messageCount: -3,
      isPinned: false,
      isEditingTitle: false,
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'SESSION_ITEM_ID_EMPTY',
      'SESSION_ITEM_TITLE_EMPTY',
      'SESSION_ITEM_MESSAGE_COUNT_NEGATIVE',
    ]);
  });
});
