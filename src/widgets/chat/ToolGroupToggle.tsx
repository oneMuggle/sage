import { ChevronDown, Wrench } from 'lucide-react';

import { useI18n } from '../../shared/lib/i18n';

export interface ToolGroupToggleProps {
  /** 工具调用总数 */
  count: number;
  /** 工具名摘要（形如 `read_file×2 · web_search`） */
  summary: string;
  /** 组内涉及的插件名（已去重） */
  owners: string[];
  expanded: boolean;
  onToggle: () => void;
}

/**
 * 工具调用折叠条 —— 把多条工具调用收成一条可展开的汇总条。
 *
 * 从 `Message.tsx` 原样抽出（DOM 结构 / className / data-testid / 文案均不变），
 * 目的是给 result 档的合并汇总条腾出架构棘轮行数。
 * result 档不使用本组件（工具调用由合并汇总条统一控制展开）。
 */
export function ToolGroupToggle({
  count,
  summary,
  owners,
  expanded,
  onToggle,
}: ToolGroupToggleProps) {
  const { t } = useI18n();
  return (
    <button
      type="button"
      data-testid="tool-calls-group-toggle"
      aria-expanded={expanded}
      onClick={onToggle}
      className="flex items-center gap-2 px-2.5 py-1.5 rounded-radius-sm border border-border bg-bg-subtle hover:bg-bg-hover text-ui-xs text-text-secondary transition-colors text-left"
    >
      <Wrench className="w-3.5 h-3.5 text-primary shrink-0" />
      <span className="font-medium text-text">已执行 {count} 步工具调用</span>
      <span className="text-text-tertiary truncate font-mono text-ui-2xs">({summary})</span>
      {owners.length > 0 && (
        <span className="text-text-tertiary shrink-0" data-testid="tool-calls-group-plugin-owners">
          {t('permission.from_plugin')}: {owners.join('、')}
        </span>
      )}
      <span className="ml-auto inline-flex items-center gap-0.5 text-ui-2xs text-primary shrink-0">
        {expanded ? '收起明细' : '展开明细'}
        <ChevronDown
          className={`w-3.5 h-3.5 transition-transform ${expanded ? 'rotate-180' : ''}`}
        />
      </span>
    </button>
  );
}
