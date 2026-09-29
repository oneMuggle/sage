// src/widgets/chat/TurnList.tsx
//
// 对标 U1（ZCode ConversationTurnNavigator）：轮次列表组件。
// 渲染 useConversationTurns 的轮次条目（序号徽标 + 用户输入预览），
// 点击经 messageJumpStore 定位滚动到该轮 user 消息。
// 样式与 ConversationOutline 同族（px-3/py-1.5/truncate/hover）。

import type { TurnItem } from '../../features/chat/useConversationTurns';

interface TurnListProps {
  items: TurnItem[];
  onSelect?: (item: TurnItem) => void;
}

export function TurnList({ items, onSelect }: TurnListProps) {
  if (items.length === 0) {
    return (
      <div className="p-3 text-sm text-muted flex flex-col items-center gap-2">
        <div>暂无轮次</div>
        <div className="text-xs text-center">对话开始后这里会列出每一轮提问</div>
      </div>
    );
  }

  return (
    <div className="py-2" data-testid="turn-list">
      {items.map((item) => (
        <button
          key={item.messageId}
          type="button"
          className="w-full text-left px-3 py-1.5 hover:bg-bg-hover transition-colors flex items-start gap-2"
          title={item.preview}
          data-testid={`turn-item-${item.index}`}
          onClick={onSelect ? () => onSelect(item) : undefined}
        >
          <span className="mt-0.5 inline-flex items-center justify-center min-w-5 h-5 px-1 rounded bg-bg-muted text-[10px] text-text-secondary">
            {item.index}
          </span>
          <span className="text-sm truncate text-text-secondary">{item.preview}</span>
        </button>
      ))}
    </div>
  );
}
