import { Brain, ChevronDown } from 'lucide-react';

import type {
  DisplayContract,
  DisplayMode,
} from '../../features/chat/displayMode/resolveDisplayMode';
import { buildResultSummaryText } from '../../features/chat/displayMode/resultSummary';
import { useI18n } from '../../shared/lib/i18n';

import { ThinkingPanel } from './MessageMarkdownParts';

export interface ThinkingDisplayProps {
  /** 是否 assistant 消息 */
  isAssistant: boolean;
  /** 思考内容（assistant 消息的 reasoning_content） */
  reasoning?: string | null;
  isStreaming?: boolean;
  mode: DisplayMode;
  contract: DisplayContract;
  /** result 档：合并汇总条是否已展开 */
  resultDetailExpanded: boolean;
  /** result 档：被收进汇总条的工具调用数量（0 = 工具调用仍逐条可见） */
  hiddenToolCount: number;
  onToggleResultDetail: () => void;
}

/**
 * 思考过程在三种展示档位下的统一渲染出口。
 *
 * - detail / trace：直接渲染 `ThinkingPanel`（契约决定默认展开态）。
 * - result：先渲染一条合并汇总条（思考过程 + 被折叠的工具调用），
 *   用户点「展开」后就地渲染 `ThinkingPanel`；工具调用的可见性由
 *   `Message.tsx` 用同一个 `resultDetailExpanded` 控制，两者同步展开。
 *
 * 无论哪个档位，被隐藏的思考内容都必须可展开（spec §1.2 约束 #1）。
 */
export function ThinkingDisplay({
  isAssistant,
  reasoning,
  isStreaming,
  mode,
  contract,
  resultDetailExpanded,
  hiddenToolCount,
  onToggleResultDetail,
}: ThinkingDisplayProps) {
  const hasReasoning = isAssistant && Boolean(reasoning);
  const hidesReasoning = mode === 'result' && hasReasoning;
  const showSummary = mode === 'result' && (hidesReasoning || hiddenToolCount > 0);
  const showPanel =
    hasReasoning && (contract.showThinkingPanel || (mode === 'result' && resultDetailExpanded));

  if (!showSummary && !showPanel) return null;

  return (
    <>
      {showSummary && (
        <ResultDetailSummary
          hasHiddenReasoning={hidesReasoning}
          hiddenToolCount={hiddenToolCount}
          expanded={resultDetailExpanded}
          onToggle={onToggleResultDetail}
        />
      )}
      {showPanel && reasoning && (
        <ThinkingPanel
          reasoning={reasoning}
          isStreaming={isStreaming}
          mode={mode}
          // result 档用户点「展开」就是要看思考内容 —— 必须默认展开，
          // 否则要点两次才能看到明细（违反 spec §6 验收标准 #2）。
          defaultExpanded={contract.showThinkingPanel ? contract.thinkingDefaultExpanded : true}
        />
      )}
    </>
  );
}

export interface ResultDetailSummaryProps {
  hasHiddenReasoning: boolean;
  hiddenToolCount: number;
  expanded: boolean;
  onToggle: () => void;
}

/** result 档合并汇总条 —— 文案随实际隐藏内容变化，点击就地展开完整明细。 */
export function ResultDetailSummary({
  hasHiddenReasoning,
  hiddenToolCount,
  expanded,
  onToggle,
}: ResultDetailSummaryProps) {
  const { t } = useI18n();
  const title = expanded
    ? t('chat.displayMode.expandedLabel')
    : buildResultSummaryText(t, { hasHiddenReasoning, hiddenToolCount });

  return (
    <button
      type="button"
      data-testid="display-mode-result-summary"
      aria-expanded={expanded}
      onClick={onToggle}
      className="mb-2 flex items-center gap-2 px-2.5 py-1.5 rounded-radius-sm border border-border bg-bg-subtle hover:bg-bg-hover text-ui-xs text-text-secondary transition-colors text-left"
    >
      <Brain className="w-3.5 h-3.5 text-primary shrink-0" />
      <span className="font-medium text-text">{title}</span>
      <span className="ml-auto inline-flex items-center gap-0.5 text-ui-2xs text-primary shrink-0">
        {expanded ? t('chat.displayMode.collapse') : t('chat.displayMode.reveal')}
        <ChevronDown
          className={`w-3.5 h-3.5 transition-transform ${expanded ? 'rotate-180' : ''}`}
        />
      </span>
    </button>
  );
}
