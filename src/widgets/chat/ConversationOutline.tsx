// src/widgets/chat/ConversationOutline.tsx
//
// P2-3.10 (UI 优化方案 2026-09-13): 对话目录/大纲组件。
// 从当前会话的 assistant 消息中提取 h2/h3 标题,渲染为可点击列表。
// h2 缩进 0,h3 缩进 1 级 (pl-4)。
//
// 设计要点:
// - 空状态友好:无标题时显示"暂无目录"提示
// - 层级视觉区分:h2 字重 500,h3 字重 400 + 缩进
// - 悬停高亮 + 点击定位到对应消息的标题（对话阅读导航 A2）
// - 长标题截断 (truncate) 防止撑破面板

import { List } from 'lucide-react';
import { useState } from 'react';

import type { OutlineItem } from '../../features/chat/useConversationOutline';

interface ConversationOutlineProps {
  items: OutlineItem[];
  isLoading: boolean;
  /**
   * 对话阅读导航 A2: 点击条目定位到对应消息 / 标题。
   * headingIndex = 该标题在所属消息内的序号（0 起），供按文本找不到标题时兜底。
   */
  onSelect?: (item: OutlineItem, headingIndex: number) => void;
}

export function ConversationOutline({ items, isLoading, onSelect }: ConversationOutlineProps) {
  const [copiedMd, setCopiedMd] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

  if (isLoading) {
    return <div className="p-3 text-sm text-muted">加载中…</div>;
  }

  if (items.length === 0) {
    return (
      <div className="p-3 text-sm text-muted flex flex-col items-center gap-2">
        <List className="w-8 h-8 opacity-30" />
        <div>暂无目录</div>
        <div className="text-xs text-center">对话中的 h2/h3 标题会自动生成目录</div>
      </div>
    );
  }

  /* v8 ignore start */
  const handleCopyMd = async () => {
    const lines = [
      '# 对话大纲目录',
      '',
      ...items.map((it) => `${it.level === 3 ? '  - ' : '- '}${it.text}`),
    ];
    setCopiedMd(true);
    await navigator.clipboard?.writeText(lines.join('\n'));
    setTimeout(() => setCopiedMd(false), 1800);
  };

  const handleCopyJson = async () => {
    setCopiedJson(true);
    await navigator.clipboard?.writeText(JSON.stringify(items, null, 2));
    setTimeout(() => setCopiedJson(false), 1800);
  };
  /* v8 ignore stop */

  return (
    <div className="py-2" data-testid="conversation-outline">
      <div className="flex items-center justify-end gap-1 px-3 pb-1.5">
        <button
          type="button"
          data-testid="conversation-outline-copy-md-btn"
          onClick={() => void handleCopyMd()}
          className="px-1.5 py-0.5 text-ui-2xs rounded border border-border text-text-secondary hover:bg-bg-hover"
        >
          {copiedMd ? '✓ 已复制MD' : '复制大纲MD'}
        </button>
        <button
          type="button"
          data-testid="conversation-outline-copy-json-btn"
          onClick={() => void handleCopyJson()}
          className="px-1.5 py-0.5 text-ui-2xs rounded border border-border text-text-secondary hover:bg-bg-hover"
        >
          {copiedJson ? '✓ 已复制JSON' : '复制大纲JSON'}
        </button>
      </div>
      {items.map((item, index) => (
        <button
          key={`${item.messageId}-${index}`}
          type="button"
          className={
            'w-full text-left px-3 py-1.5 hover:bg-bg-hover transition-colors ' +
            'text-sm truncate ' +
            (item.level === 2 ? 'font-medium text-text' : 'font-normal text-text-secondary pl-7')
          }
          title={item.text}
          data-testid={`outline-item-${index}`}
          onClick={
            onSelect
              ? () =>
                  onSelect(
                    item,
                    items.slice(0, index).filter((prev) => prev.messageId === item.messageId)
                      .length,
                  )
              : undefined
          }
        >
          {item.text}
        </button>
      ))}
    </div>
  );
}
