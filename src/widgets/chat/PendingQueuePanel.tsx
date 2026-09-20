import { ChevronDown, ChevronUp, GripVertical, ListOrdered, Play, X } from 'lucide-react';
import { memo, useRef, useState } from 'react';

import type { QueuedChatMessage } from '../../features/send-message/chatStreamStore';
import { useI18n } from '../../shared/lib/i18n';

interface PendingQueuePanelProps {
  items: readonly QueuedChatMessage[];
  /** 上一轮以错误/中断收尾 → 自动发送已暂停，等用户显式继续 */
  paused: boolean;
  onSendNow: (id: string) => void;
  onEdit: (id: string) => void;
  onMoveToFront: (id: string) => void;
  /** 拖拽落点：把 fromId 这条移动到 toId 当前所在下标。 */
  onReorder: (fromId: string, toId: string) => void;
  onRemove: (id: string) => void;
  onClear: () => void;
  onResume: () => void;
}

/**
 * U5 (2026-09-18): 待发送队列面板。
 *
 * 队列此前只活在一个 toast 里——用户看不见有几条在等、无法改顺序、
 * 删掉误发的条目，出错暂停后更是完全不知道消息去了哪。这里把这些
 * 操作显式化：拖拽排序 / 置顶 / 立即发送（会先停掉当前回复）/ 编辑 /
 * 删除 / 清空，并在标题下写清"什么时候发出去"。
 *
 * 拖拽排序用原生 HTML5 drag events（main 在 PR #1356 移除了 @dnd-kit，
 * 队列排序是面板内部状态，无需引入新的 dnd 依赖）。
 */
function PendingQueuePanelInner({
  items,
  paused,
  onSendNow,
  onEdit,
  onMoveToFront,
  onReorder,
  onRemove,
  onClear,
  onResume,
}: PendingQueuePanelProps) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(true);
  const dragFromId = useRef<string | null>(null);

  if (items.length === 0) return null;

  return (
    <div
      data-testid="pending-queue"
      className="mx-4 mb-1 rounded-t-radius-md border border-b-0 border-border bg-bg-secondary"
    >
      <button
        type="button"
        data-testid="pending-queue-toggle"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-text-secondary hover:bg-bg-hover transition-colors"
      >
        <ListOrdered className="w-3.5 h-3.5" />
        <span className="font-medium">
          {t('chat.queue_title')} · {items.length}
        </span>
        {paused && (
          <span data-testid="pending-queue-paused" className="text-warning">
            {t('chat.queue_paused')}
          </span>
        )}
        <span className="flex-1" />
        {paused && (
          <span
            role="button"
            tabIndex={0}
            data-testid="pending-queue-resume"
            onClick={(e) => {
              e.stopPropagation();
              onResume();
            }}
            onKeyDown={(e) => {
              if (e.key !== 'Enter') return;
              e.stopPropagation();
              onResume();
            }}
            className="px-1.5 py-0.5 rounded text-primary hover:bg-bg cursor-pointer"
          >
            {t('chat.queue_resume')}
          </span>
        )}
        <span
          role="button"
          tabIndex={0}
          data-testid="pending-queue-clear"
          onClick={(e) => {
            e.stopPropagation();
            onClear();
          }}
          onKeyDown={(e) => {
            if (e.key !== 'Enter') return;
            e.stopPropagation();
            onClear();
          }}
          className="px-1.5 py-0.5 rounded hover:bg-bg cursor-pointer"
        >
          {t('chat.queue_clear')}
        </span>
        {expanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronUp className="w-3.5 h-3.5" />}
      </button>

      <div
        data-testid="pending-queue-timing"
        className="px-3 pb-1.5 -mt-0.5 text-ui-2xs text-text-muted"
      >
        {t(paused ? 'chat.queue_timing_paused' : 'chat.queue_timing')}
      </div>

      {expanded && (
        <div className="px-2 pb-2 space-y-1">
          {items.map((item, idx) => (
            <div
              key={item.id}
              data-testid="pending-queue-item"
              draggable
              onDragStart={(e) => {
                dragFromId.current = item.id;
                e.dataTransfer.effectAllowed = 'move';
                e.dataTransfer.setData('text/plain', item.id);
              }}
              onDragOver={(e) => {
                e.preventDefault();
                e.dataTransfer.dropEffect = 'move';
              }}
              onDrop={(e) => {
                e.preventDefault();
                const fromId = dragFromId.current;
                if (fromId && fromId !== item.id) {
                  onReorder(fromId, item.id);
                }
                dragFromId.current = null;
              }}
              onDragEnd={() => {
                dragFromId.current = null;
              }}
              className="flex items-center gap-2 px-2 py-1 rounded-radius-sm bg-bg text-xs text-text"
            >
              <button
                type="button"
                aria-label={t('sider.drag_handle')}
                title={t('sider.drag_handle')}
                className="inline-flex items-center justify-center w-5 h-5 flex-shrink-0 cursor-grab active:cursor-grabbing text-muted hover:text-text"
                tabIndex={-1}
              >
                <GripVertical className="w-3.5 h-3.5" />
              </button>
              <span className="text-text-muted tabular-nums w-4 flex-shrink-0">{idx + 1}</span>
              <span className="flex-1 truncate" title={item.content}>
                {item.content}
              </span>
              <button
                type="button"
                data-testid="pending-queue-send-now"
                onClick={() => onSendNow(item.id)}
                title={t('chat.queue_send_now')}
                aria-label={t('chat.queue_send_now')}
                className="p-1 rounded hover:bg-bg-hover text-primary cursor-pointer"
              >
                <Play className="w-3.5 h-3.5" />
              </button>
              {idx > 0 && (
                <button
                  type="button"
                  data-testid="pending-queue-top"
                  onClick={() => onMoveToFront(item.id)}
                  title={t('chat.queue_top')}
                  aria-label={t('chat.queue_top')}
                  className="p-1 rounded hover:bg-bg-hover text-text-secondary cursor-pointer"
                >
                  <ChevronUp className="w-3.5 h-3.5" />
                </button>
              )}
              <button
                type="button"
                data-testid="pending-queue-edit"
                onClick={() => onEdit(item.id)}
                title={t('chat.queue_edit')}
                aria-label={t('chat.queue_edit')}
                className="px-1 rounded hover:bg-bg-hover text-text-secondary cursor-pointer"
              >
                {t('chat.queue_edit')}
              </button>
              <button
                type="button"
                data-testid="pending-queue-remove"
                onClick={() => onRemove(item.id)}
                title={t('chat.queue_remove')}
                aria-label={t('chat.queue_remove')}
                className="p-1 rounded hover:bg-bg-hover text-text-secondary cursor-pointer"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export const PendingQueuePanel = memo(PendingQueuePanelInner);
