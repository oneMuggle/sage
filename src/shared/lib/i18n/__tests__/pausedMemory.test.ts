import { describe, expect, it } from 'vitest';

import {
  formatPausedMemoryI18nJson,
  formatPausedMemoryI18nSummary,
  pausedMemoryEn,
  pausedMemoryZh,
} from '../pausedMemory';

describe('pausedMemory i18n audit diagnostics', () => {
  it('formats pausedMemory i18n summary with full parity', () => {
    expect(formatPausedMemoryI18nSummary()).toBe('zh=7 · en=7 · parity=true');
    expect(Object.keys(pausedMemoryZh)).toEqual(Object.keys(pausedMemoryEn));
  });

  it('serializes pausedMemory i18n audit JSON', () => {
    const parsed = JSON.parse(formatPausedMemoryI18nJson());
    expect(parsed.zhCount).toBe(7);
    expect(parsed.enCount).toBe(7);
    expect(parsed.parity).toBe(true);
    expect(parsed.keys).toContain('chat.temp_chat');
  });
});
