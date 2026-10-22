import { describe, expect, it } from 'vitest';

import {
  auditFontOptionsGovernance,
  FONT_DEFAULTS,
  FONT_SIZE_MAX,
  FONT_SIZE_MIN,
} from '../fontOptions';

describe('fontOptions P153 governance audit', () => {
  it('returns healthy defaults for fontOptions governance', () => {
    const res = auditFontOptionsGovernance();
    expect(res.module).toBe('src/entities/font/fontOptions.ts');
    expect(res.phase).toBe('P153');
    expect(res.uiSize).toBe(FONT_DEFAULTS.fontSizeUi);
    expect(res.codeSize).toBe(FONT_DEFAULTS.fontSizeCode);
    expect(res.healthy).toBe(true);
  });

  it('clamps uiSize and codeSize into valid font bounds', () => {
    const res = auditFontOptionsGovernance({
      uiSize: 4,
      codeSize: 80,
    });
    expect(res.uiSize).toBe(FONT_SIZE_MIN);
    expect(res.codeSize).toBe(FONT_SIZE_MAX);
    expect(res.healthy).toBe(true);
  });
});
