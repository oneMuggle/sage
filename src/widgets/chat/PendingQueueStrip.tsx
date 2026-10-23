// src/widgets/chat/PendingQueueStrip.tsx
//
// P1-6 (主流 AI UX 方案 §5): 排队/转向意图可见化。
//
// 背景：流式输出期间用户继续发送，useChat 会先把消息塞进队列，当前回复
// 一结束就**自动连发**下一条。这条链路原本唯一的用户可见信号是一条 4 秒
// 即逝的 toast —— 队列里到底有几条、分别是什么，用户无从得知，也撤不掉。
//
// 这不只是体验问题，还是诚实性问题：错误/中断路径刻意不 flush 队列
//（连续失败时自动重发只会重复报错），于是这些消息会静默滞留成「僵尸队列」，
// 可能在很久之后被下一条无关的正常流意外带发。一个用户看不见、撤不掉、
// 会在他不知情时自动发送的消息队列，违反 PHILOSOPHY 的「透明可控」。
//
// 因此队列必须常驻可见，且每一条都能在真正发出去之前撤回。
// 已有的转向（steer）路径本身有 toast 反馈且会立即生效，无需另设 UI。

export interface PendingQueueItem {
  id: string;
  content: string;
}

interface PendingQueueStripProps {
  /** 当前会话排队中的消息（按入队顺序） */
  items: PendingQueueItem[];
  /** 撤回单条 */
  onCancel: (id: string) => void;
  /** 清空全部 */
  onClearAll: () => void;
}

export function PendingQueueStrip({ items, onCancel, onClearAll }: PendingQueueStripProps) {
  if (items.length === 0) return null;

  return (
    <div
      data-testid="pending-queue-strip"
      role="status"
      aria-label="排队待发送消息"
      className="flex flex-col gap-1 px-3 pt-2 shrink-0"
    >
      <div className="flex items-center gap-2 text-ui-2xs text-text-tertiary">
        <span data-testid="pending-queue-count">已排队 {items.length} 条</span>
        <span className="text-text-tertiary">· 当前回复结束后自动发送</span>
        <button
          type="button"
          data-testid="pending-queue-clear-all"
          onClick={onClearAll}
          className="ml-auto px-1.5 py-0.5 rounded-radius-sm border border-border text-text-tertiary hover:text-text hover:bg-bg-hover transition-colors shrink-0"
        >
          全部清空
        </button>
      </div>
      <ul className="flex flex-col gap-1 max-h-32 overflow-y-auto">
        {items.map((item) => (
          <li
            key={item.id}
            data-testid="pending-queue-item"
            className="flex items-center gap-2 px-2 py-1 rounded-radius-sm bg-bg-secondary text-ui-xs text-text-secondary"
          >
            <span className="truncate flex-1" title={item.content}>
              {item.content}
            </span>
            <button
              type="button"
              data-testid="pending-queue-cancel"
              aria-label={`撤回排队消息：${item.content}`}
              onClick={() => onCancel(item.id)}
              className="shrink-0 text-text-tertiary hover:text-text transition-colors"
            >
              撤回
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
