// src/features/chat/useConversationOutline.ts
//
// P2-3.10 (UI 优化方案 2026-09-13): 从当前会话的 assistant 消息中提取
// h2/h3 标题,生成对话大纲。点击大纲条目可滚动到对应消息。
//
// 数据源: useStore 的 messages (按 session_id 过滤)
// 输出: OutlineItem[] (标题文本 + 消息 ID + 层级)

import { useMemo } from 'react';

import { useStore } from '../../shared/lib/store';

export interface OutlineItem {
  /** 标题文本 (不含 ## 前缀) */
  text: string;
  /** 所属消息 ID (用于滚动定位) */
  messageId: string;
  /** 标题层级: 2 = h2, 3 = h3 */
  level: 2 | 3;
}

/**
 * 从 markdown 文本提取 h2/h3 标题。
 * 支持 ATX 风格: ## Title 或 ### Title
 * 忽略代码块内的标题 (# 在 ``` 内)
 */
function extractHeadings(markdown: string): Array<{ text: string; level: 2 | 3 }> {
  const headings: Array<{ text: string; level: 2 | 3 }> = [];
  const lines = markdown.split('\n');
  let inCodeBlock = false;

  for (const line of lines) {
    // 跟踪代码块状态 (``` 或 ~~~)
    if (line.trimStart().startsWith('```') || line.trimStart().startsWith('~~~')) {
      inCodeBlock = !inCodeBlock;
      continue;
    }

    if (inCodeBlock) continue;

    // 匹配 ## 或 ### (不匹配 # 或 ####+)
    const match = line.match(/^(#{2,3})\s+(.+)$/);
    if (match) {
      const level = match[1].length as 2 | 3;
      const text = match[2].trim();
      if (text) {
        headings.push({ text, level });
      }
    }
  }

  return headings;
}

/**
 * 获取当前会话的对话大纲。
 * 返回 assistant 消息中的 h2/h3 标题列表。
 */
export function useConversationOutline(sessionId: string | null): {
  items: OutlineItem[];
  isLoading: boolean;
} {
  const messages = useStore((s) => s.messages);
  const isLoading = useStore((s) => s.isLoading);

  const items = useMemo(() => {
    if (!sessionId) return [];

    const outlineItems: OutlineItem[] = [];

    for (const msg of messages) {
      if (msg.session_id !== sessionId || msg.role !== 'assistant') continue;
      if (!msg.content) continue;

      const headings = extractHeadings(msg.content);
      for (const h of headings) {
        outlineItems.push({
          text: h.text,
          messageId: msg.id,
          level: h.level,
        });
      }
    }

    return outlineItems;
  }, [messages, sessionId]);

  return { items, isLoading };
}
