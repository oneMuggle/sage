// src/widgets/chat/ConversationOutline.tsx
//
// P2-3.10 (UI 优化方案 2026-09-13): 对话目录/大纲组件。
// 从当前会话的 assistant 消息中提取 h2/h3 标题,渲染为可点击列表。
// h2 缩进 0,h3 缩进 1 级 (pl-4)。
//
// 设计要点:
// - 空状态友好:无标题时显示"暂无目录"提示
// - 层级视觉区分:h2 字重 500,h3 字重 400 + 缩进
// - 悬停高亮 + cursor-pointer (未来可扩展滚动定位)
// - 长标题截断 (truncate) 防止撑破面板

import { List } from 'lucide-react';

import type { OutlineItem } from '../../features/chat/useConversationOutline';

interface ConversationOutlineProps {
  items: OutlineItem[];
  isLoading: boolean;
}

export function ConversationOutline({ items, isLoading }: ConversationOutlineProps) {
  if (isLoading) {
    return (
      <div className="p-3 text-sm text-muted">加载中…</div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="p-3 text-sm text-muted flex flex-col items-center gap-2">
        <List className="w-8 h-8 opacity-30" />
        <div>暂无目录</div>
        <div className="text-xs text-center">
          对话中的 h2/h3 标题会自动生成目录
        </div>
      </div>
    );
  }

  return (
    <div className="py-2" data-testid="conversation-outline">
      {items.map((item, index) => (
        <button
          key={`${item.messageId}-${index}`}
          className={
            'w-full text-left px-3 py-1.5 hover:bg-bg-hover transition-colors ' +
            'text-sm truncate ' +
            (item.level === 2
              ? 'font-medium text-text'
              : 'font-normal text-text-secondary pl-7')
          }
          title={item.text}
          data-testid={`outline-item-${index}`}
          // 未来扩展: onClick={() => scrollToMessage(item.messageId)}
        >
          {item.text}
        </button>
      ))}
    </div>
  );
}
