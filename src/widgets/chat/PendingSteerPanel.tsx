import { MessageSquarePlus, X } from 'lucide-react';
import { memo } from 'react';

import type { PendingSteerItem } from '../../features/send-message/chatStreamStore';
import { useI18n } from '../../shared/lib/i18n';

interface PendingSteerPanelProps {
  items: readonly PendingSteerItem[];
  /** 撤回一条尚未被 AI 消费的插话。 */
  onCancel: (id: string) => void;
}

/**
 * 2026-11-07: 插话暂存区面板。
 *
 * 插话此前是"发出去就消失"——用户无法确认 AI 到底有没有收到、更无法在
 * AI 消费前收回。这里把已注入 run、但尚未在迭代边界被消费的插话临时挂在
 * 输入框上方：点 X 撤回（后端不会落库，等同未送达）；AI 消费后后端回推
 * steer_consumed，chip 自动消失并落入聊天区。
 */
function PendingSteerPanelInner({ items, onCancel }: PendingSteerPanelProps) {
  const { t } = useI18n();

  if (items.length === 0) return null;

  return (
    <div
      data-testid="pending-steer"
      className="mx-4 mb-1 rounded-t-radius-md border border-b-0 border-border bg-bg-secondary"
    >
      <div className="flex items-center gap-2 px-3 py-1.5 text-xs text-text-secondary">
        <MessageSquarePlus className="w-3.5 h-3.5" />
        <span className="font-medium">
          {t('chat.steer_pending_title')} · {items.length}
        </span>
      </div>

      <div
        data-testid="pending-steer-hint"
        className="px-3 pb-1.5 -mt-0.5 text-ui-2xs text-text-muted"
      >
        {t('chat.steer_pending_hint')}
      </div>

      <div className="px-2 pb-2 space-y-1">
        {items.map((item) => (
          <div
            key={item.id}
            data-testid="pending-steer-item"
            className="flex items-center gap-2 px-2 py-1 rounded-radius-sm bg-bg text-xs text-text"
          >
            <span className="flex-1 truncate" title={item.content}>
              {item.content}
            </span>
            <button
              type="button"
              data-testid="pending-steer-cancel"
              onClick={() => onCancel(item.id)}
              title={t('chat.steer_pending_cancel')}
              aria-label={t('chat.steer_pending_cancel')}
              className="p-1 rounded hover:bg-bg-hover text-text-secondary cursor-pointer"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

export const PendingSteerPanel = memo(PendingSteerPanelInner);
