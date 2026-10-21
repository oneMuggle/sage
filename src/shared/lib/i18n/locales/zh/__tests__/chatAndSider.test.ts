import { describe, expect, it } from 'vitest';

import {
  formatZhChatAndSiderJson,
  formatZhChatAndSiderSummary,
  zhChatAndSider,
} from '../chatAndSider';

describe('zhChatAndSider domain locale audit diagnostics', () => {
  it('formats zh.chatAndSider summary', () => {
    const count = Object.keys(zhChatAndSider).length;
    expect(count).toBeGreaterThan(50);
    expect(formatZhChatAndSiderSummary()).toBe(`domain=zh.chatAndSider · keys=${count}`);
  });

  it('serializes zh.chatAndSider audit JSON', () => {
    const parsed = JSON.parse(formatZhChatAndSiderJson());
    expect(parsed).toEqual({
      domain: 'zh.chatAndSider',
      keyCount: Object.keys(zhChatAndSider).length,
    });
  });
});
