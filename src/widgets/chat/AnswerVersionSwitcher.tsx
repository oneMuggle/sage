// 对话阅读体验 C2（docs/mcp-chat-reading-nav-optimization.md §10.6）：最后一条 assistant
// 消息操作栏里的回答版本切换 ‹ 2/3 ›。只有一个版本时不渲染。
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import {
  activateAnswerVersion,
  fetchAnswerVersions,
  type AnswerVersionList,
} from '../../features/chat/answerVersions';
import { fillTemplate } from '../../shared/lib/fillTemplate';
import { useI18n } from '../../shared/lib/i18n';

interface AnswerVersionSwitcherProps {
  sessionId: string;
  /** 最后一条 assistant 消息 id：新回答或切换后重拉消息时随之变化，触发刷新 */
  messageId: string;
  /** 切换成功后回调（Chat 重拉消息） */
  onChanged: () => void;
}

export function AnswerVersionSwitcher({
  sessionId,
  messageId,
  onChanged,
}: AnswerVersionSwitcherProps) {
  const { t } = useI18n();
  const [list, setList] = useState<AnswerVersionList | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchAnswerVersions(sessionId)
      .then((result) => {
        if (!cancelled) setList(result);
      })
      .catch(() => {
        // 演示模式 / 后端不可用：不显示切换器
        if (!cancelled) setList(null);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId, messageId]);

  if (!list || list.total <= 1 || list.current_index < 1) return null;

  const current = list.current_index;
  const go = async (delta: -1 | 1) => {
    const target = list.versions[current - 1 + delta];
    if (!target || target.current || busy) return;
    setBusy(true);
    try {
      await activateAnswerVersion(sessionId, target.id);
      onChanged();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      toast.error(fillTemplate(t('chat.version_switch_failed'), { message }));
    } finally {
      setBusy(false);
    }
  };

  const label = fillTemplate(t('chat.version_label'), { current, total: list.total });
  return (
    <div
      role="group"
      aria-label={label}
      data-testid="answer-version-switcher"
      className="flex items-center mr-1 text-xs text-text-muted select-none"
    >
      <button
        type="button"
        data-testid="answer-version-prev"
        onClick={() => void go(-1)}
        disabled={busy || current <= 1}
        className="p-1 rounded hover:bg-bg-hover disabled:opacity-40 disabled:cursor-default"
        title={t('chat.version_prev')}
        aria-label={t('chat.version_prev')}
      >
        <ChevronLeft className="w-3.5 h-3.5" />
      </button>
      <span data-testid="answer-version-count" className="tabular-nums" title={label}>
        {current}/{list.total}
      </span>
      <button
        type="button"
        data-testid="answer-version-next"
        onClick={() => void go(1)}
        disabled={busy || current >= list.total}
        className="p-1 rounded hover:bg-bg-hover disabled:opacity-40 disabled:cursor-default"
        title={t('chat.version_next')}
        aria-label={t('chat.version_next')}
      >
        <ChevronRight className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}
