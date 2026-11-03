import { describe, expect, it } from 'vitest';

import type { TranslationKey } from '../../../../shared/lib/i18n';
import { zh } from '../../../../shared/lib/i18n/zh';
import { buildResultSummaryText } from '../resultSummary';

/** 用真实的 zh 词典当真值来源，避免测试里再抄一份文案。 */
const dict = zh as Record<string, string>;
const t = (key: TranslationKey): string => dict[key] ?? key;

describe('buildResultSummaryText', () => {
  it('mentions both reasoning and tool calls when both are hidden', () => {
    expect(buildResultSummaryText(t, { hasHiddenReasoning: true, hiddenToolCount: 3 })).toBe(
      '已隐藏思考过程与 3 步工具调用',
    );
  });

  it('mentions only reasoning when no tool calls are hidden', () => {
    expect(buildResultSummaryText(t, { hasHiddenReasoning: true, hiddenToolCount: 0 })).toBe(
      '已隐藏思考过程',
    );
  });

  it('mentions only tool calls when reasoning is not hidden', () => {
    expect(buildResultSummaryText(t, { hasHiddenReasoning: false, hiddenToolCount: 3 })).toBe(
      '已隐藏 3 步工具调用',
    );
  });

  it('returns an empty string when nothing is hidden', () => {
    expect(buildResultSummaryText(t, { hasHiddenReasoning: false, hiddenToolCount: 0 })).toBe('');
  });
});
