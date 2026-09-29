// src/widgets/chat/ChatNoticeStack.tsx
//
// UX-IA R1 批次 B（docs/plans/2026-09-29_ux-ia-round1-batch-b.md）：
// 聊天区顶部的会话级提示（对话出错 / 运行中断 / 话题切换）原本各自独立堆叠，
// 最坏情况下同时出现 3 条横幅，把消息区往下挤。对标 ChatGPT / Claude 的
// 「同一时刻只打扰一次」：按优先级只展示最重要的一条，其余折叠为
// 「另有 N 条提示」，点击后展开全部。每条提示自身的交互（重试 / 忽略 /
// 恢复）完全保留，由调用方传入的节点负责。

import { useState, type ReactNode } from 'react';

export interface ChatNotice {
  /** 稳定 key（同时作为 data-notice-key） */
  key: string;
  /** 数值越大越优先展示 */
  priority: number;
  node: ReactNode;
}

/** 预置优先级：错误 > 中断 > 话题切换 */
export const CHAT_NOTICE_PRIORITY = {
  error: 30,
  interrupted: 20,
  topicShift: 10,
} as const;

interface ChatNoticeStackProps {
  notices: ReadonlyArray<ChatNotice | false | null | undefined>;
}

export function ChatNoticeStack({ notices }: ChatNoticeStackProps) {
  const [expanded, setExpanded] = useState(false);
  const active = notices
    .filter((n): n is ChatNotice => Boolean(n))
    .sort((a, b) => b.priority - a.priority);

  if (active.length === 0) return null;

  const [primary, ...rest] = active;
  const visible = expanded ? active : [primary];

  return (
    <div data-testid="chat-notice-stack" className="shrink-0">
      {visible.map((n) => (
        <div key={n.key} data-notice-key={n.key}>
          {n.node}
        </div>
      ))}
      {rest.length > 0 && (
        <button
          type="button"
          data-testid="chat-notice-toggle"
          aria-expanded={expanded}
          onClick={() => setExpanded((v) => !v)}
          className="w-full px-5 py-1 text-left text-xs text-text-secondary hover:text-text-primary hover:bg-bg-hover border-b border-border transition-colors"
        >
          {expanded ? '收起其他提示' : `另有 ${rest.length} 条提示`}
        </button>
      )}
    </div>
  );
}
