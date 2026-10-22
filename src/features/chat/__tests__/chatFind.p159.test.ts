import { describe, expect, it } from 'vitest';

import {
  auditChatFindGovernance,
  buildChatFindAuditJson,
  CHAT_FIND_EVENT,
  FOCUS_SEARCH_EVENT,
} from '../chatFind';

describe('chatFind governance audit (P159)', () => {
  it('verifies chat find events and case-insensitive occurrence counter', () => {
    const report = auditChatFindGovernance();
    expect(report.module).toBe('features.chat.chatFind');
    expect(report.phase).toBe('P159');
    expect(report.findEventName).toBe(CHAT_FIND_EVENT);
    expect(report.focusSearchEventName).toBe(FOCUS_SEARCH_EVENT);
    expect(report.sampleMatchCount).toBe(2);
    expect(report.healthy).toBe(true);
  });

  it('maintains JSON audit helper serialization', () => {
    const raw = buildChatFindAuditJson();
    expect(JSON.parse(raw)).toBeTruthy();
  });
});
