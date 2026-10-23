import { describe, expect, it } from 'vitest';

import { auditZhChatAndSiderGovernance } from '../i18n/locales/zh/chatAndSider';

describe('auditZhChatAndSiderGovernance (Phase P183)', () => {
  it('returns deterministic P183 governance audit payload', () => {
    const payload = JSON.parse(auditZhChatAndSiderGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('zh-chat-and-sider');
    expect(payload.phase).toBe('P183');
    expect(payload.audited).toBe(true);
  });
});
