// 对话阅读体验 B2（docs/mcp-chat-reading-nav-optimization.md §10.4）：回答因触达
// 输出上限被截断时的提示；是会话最后一条消息时附带「继续生成」。
import { AlertTriangle } from 'lucide-react';

import { useI18n } from '../../shared/lib/i18n';

/** OpenAI 风格为 length；个别兼容端点透传厂商原值 max_tokens */
const TRUNCATED_REASONS = new Set(['length', 'max_tokens']);

interface TruncationNoticeProps {
  finishReason?: string | null;
  /** 提供时显示「继续生成」按钮（仅会话最后一条消息） */
  onContinue?: () => void;
}

export function TruncationNotice({ finishReason, onContinue }: TruncationNoticeProps) {
  const { t } = useI18n();
  if (!finishReason || !TRUNCATED_REASONS.has(finishReason)) return null;
  return (
    <div
      className="flex items-center gap-2 mt-1 text-[11px] text-warning"
      data-testid="message-truncated"
    >
      <AlertTriangle className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
      <span>{t('chat.truncated_notice')}</span>
      {onContinue && (
        <button
          type="button"
          onClick={onContinue}
          className="px-2 py-0.5 rounded border border-border text-text-secondary hover:bg-bg-hover"
          data-testid="continue-generating"
        >
          {t('chat.continue_generating')}
        </button>
      )}
    </div>
  );
}
