import { describe, expect, it } from 'vitest';

import { auditChatHeaderBarGovernance } from '../ChatHeaderBar';

describe('auditChatHeaderBarGovernance (P172)', () => {
  it('returns compliant governance audit metadata for ChatHeaderBar', () => {
    const report = auditChatHeaderBarGovernance();
    expect(report.module).toBe('src/pages/chat/ChatHeaderBar.tsx');
    expect(report.phase).toBe('P172');
    expect(report.domain).toBe('chat');
    expect(report.topHeaderControls).toHaveLength(5);
    expect(report.compliant).toBe(true);
  });
});
