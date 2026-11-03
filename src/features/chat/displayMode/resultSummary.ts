import { fillTemplate } from '../../../shared/lib/fillTemplate';
import type { TranslationKey } from '../../../shared/lib/i18n';

export interface ResultSummaryInput {
  /** 思考过程是否被收进汇总条 */
  hasHiddenReasoning: boolean;
  /** 被收进汇总条的工具调用数量（0 = 工具调用仍逐条可见） */
  hiddenToolCount: number;
}

/** result 档汇总条文案 —— 随实际隐藏内容变化（spec §3.3「文案随实际内容变化」）。 */
export function buildResultSummaryText(
  t: (key: TranslationKey) => string,
  input: ResultSummaryInput,
): string {
  const { hasHiddenReasoning, hiddenToolCount } = input;
  if (hasHiddenReasoning && hiddenToolCount > 0) {
    return fillTemplate(t('chat.displayMode.hiddenSummary'), { count: hiddenToolCount });
  }
  if (hasHiddenReasoning) return t('chat.displayMode.hiddenReasoning');
  if (hiddenToolCount > 0) {
    return fillTemplate(t('chat.displayMode.hiddenToolCalls'), { count: hiddenToolCount });
  }
  return '';
}
