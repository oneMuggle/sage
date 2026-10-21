import { describe, expect, it } from 'vitest';

import {
  enChatAndSider,
  formatEnChatAndSiderJson,
  formatEnChatAndSiderSummary,
} from '../chatAndSider';

describe('enChatAndSider domain locale audit diagnostics', () => {
  it('formats en.chatAndSider summary', () => {
    const count = Object.keys(enChatAndSider).length;
    expect(count).toBeGreaterThan(50);
    expect(formatEnChatAndSiderSummary()).toBe(`domain=en.chatAndSider · keys=${count}`);
  });

  it('serializes en.chatAndSider audit JSON', () => {
    const parsed = JSON.parse(formatEnChatAndSiderJson());
    expect(parsed).toEqual({
      domain: 'en.chatAndSider',
      keyCount: Object.keys(enChatAndSider).length,
    });
  });
});
