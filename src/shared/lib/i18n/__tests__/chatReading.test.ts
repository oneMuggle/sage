import { describe, expect, it } from 'vitest';

import {
  chatReadingZh,
  chatReadingEn,
  formatChatReadingI18nSummary,
  formatChatReadingI18nJson,
} from '../chatReading';

describe('chatReading i18n audit helpers', () => {
  it('verifies zh/en key parity and formats summary and json', () => {
    const count = Object.keys(chatReadingZh).length;
    expect(Object.keys(chatReadingEn).length).toBe(count);
    expect(formatChatReadingI18nSummary()).toBe(
      `zh=${count} · en=${count} · parity=true`,
    );
    const parsed = JSON.parse(formatChatReadingI18nJson());
    expect(parsed).toEqual({
      zhKeyCount: count,
      enKeyCount: count,
      parity: true,
    });
  });

  it('exposes expected reading keys in both locales', () => {
    expect(chatReadingZh['chat.read_aloud']).toBe('朗读');
    expect(chatReadingEn['chat.read_aloud']).toBe('Read aloud');
  });
});
