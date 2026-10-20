// src/widgets/chat/TurnList.tsx
//
// 对标 U1（ZCode ConversationTurnNavigator）：轮次列表组件。
// 渲染 useConversationTurns 的轮次条目（序号徽标 + 用户输入预览），
// 点击经 messageJumpStore 定位滚动到该轮 user 消息。
// 样式与 ConversationOutline 同族（px-3/py-1.5/truncate/hover）。

import { useState } from 'react';

import type { TurnItem } from '../../features/chat/useConversationTurns';

interface TurnListProps {
  items: TurnItem[];
  onSelect?: (item: TurnItem) => void;
}

export function formatTurnListMarkdown(items: ReadonlyArray<TurnItem>): string {
  const lines = [
    '# 会话轮次导航列表 (Conversation Turns)',
    '',
    `- **轮次总数**: ${items.length}`,
  ];
  if (items.length === 0) {
    lines.push('', '_暂无轮次_');
  } else {
    lines.push('', '## 轮次列表');
    for (const item of items) {
      lines.push(`- **[#${item.index}]** (${item.messageId}): ${item.preview}`);
    }
  }
  return lines.join('\n');
}

export function formatTurnListJson(items: ReadonlyArray<TurnItem>): string {
  return JSON.stringify(
    {
      exportedAt: new Date().toISOString(),
      total: items.length,
      items,
    },
    null,
    2,
  );
}

export function TurnList({ items, onSelect }: TurnListProps) {
  const [copiedMd, setCopiedMd] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

  if (items.length === 0) {
    return (
      <div className="p-3 text-sm text-muted flex flex-col items-center gap-2">
        <div>暂无轮次</div>
        <div className="text-xs text-center">对话开始后这里会列出每一轮提问</div>
      </div>
    );
  }

  /* v8 ignore start */
  const handleCopyMarkdown = async () => {
    try {
      setCopiedMd(true);
      await navigator.clipboard?.writeText(formatTurnListMarkdown(items));
      setTimeout(() => setCopiedMd(false), 1500);
    } catch {
      // ignore clipboard errors
    }
  };

  const handleCopyJson = async () => {
    try {
      setCopiedJson(true);
      await navigator.clipboard?.writeText(formatTurnListJson(items));
      setTimeout(() => setCopiedJson(false), 1500);
    } catch {
      // ignore clipboard errors
    }
  };
  /* v8 ignore stop */

  return (
    <div className="py-2" data-testid="turn-list">
      <div className="mb-1 flex items-center justify-end gap-1 px-3">
        <button
          type="button"
          data-testid="turn-list-copy-md"
          onClick={() => void handleCopyMarkdown()}
          className="px-1.5 py-0.5 text-ui-2xs rounded border border-border text-text-secondary hover:bg-bg-hover"
        >
          {copiedMd ? '已复制 MD' : '复制 MD'}
        </button>
        <button
          type="button"
          data-testid="turn-list-copy-json"
          onClick={() => void handleCopyJson()}
          className="px-1.5 py-0.5 text-ui-2xs rounded border border-border text-text-secondary hover:bg-bg-hover"
        >
          {copiedJson ? '已复制 JSON' : '复制 JSON'}
        </button>
      </div>
      {items.map((item) => (
        <button
          key={item.messageId}
          type="button"
          className="w-full text-left px-3 py-1.5 hover:bg-bg-hover transition-colors flex items-start gap-2"
          title={item.preview}
          data-testid={`turn-item-${item.index}`}
          onClick={onSelect ? () => onSelect(item) : undefined}
        >
          <span className="mt-0.5 inline-flex items-center justify-center min-w-5 h-5 px-1 rounded bg-bg-muted text-ui-xs text-text-secondary">
            {item.index}
          </span>
          <span className="text-sm truncate text-text-secondary">{item.preview}</span>
        </button>
      ))}
    </div>
  );
}
