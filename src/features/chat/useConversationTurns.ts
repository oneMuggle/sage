// src/features/chat/useConversationTurns.ts
//
// 对标 U1（ZCode ConversationTurnNavigator）：轮次导航数据源。
// 每条普通 user 消息（role='user' 且无 subtype）即一轮对话的开始；
// tool 回显与话题段切换 marker（subtype='topic_separator'）不算轮次。
//
// 输出: TurnItem[]（1 起的轮次序号 + 起始消息 ID + 用户输入预览），
// 供 RightPanel「轮次」分组点击后经 messageJumpStore 定位滚动。

import { useMemo } from 'react';

import { useStore } from '../../shared/lib/store';

/** 用户输入预览的最大字符数（换行折叠为空格） */
export const TURN_PREVIEW_MAX_CHARS = 48;

export interface TurnItem {
  /** 1 起的轮次序号 */
  index: number;
  /** 该轮起始 user 消息 ID（跳转目标） */
  messageId: string;
  /** 用户输入预览（换行折叠、超长截断加 …） */
  preview: string;
}

function toPreview(content: string): string {
  const flat = content.replace(/\s+/g, ' ').trim();
  if (flat.length <= TURN_PREVIEW_MAX_CHARS) return flat;
  return flat.slice(0, TURN_PREVIEW_MAX_CHARS) + '…';
}

/**
 * 获取当前会话的轮次列表（每轮 = 一条普通 user 消息）。
 */
export function useConversationTurns(sessionId: string | null): {
  items: TurnItem[];
} {
  const messages = useStore((s) => s.messages);

  const items = useMemo(() => {
    if (!sessionId) return [];

    const turnItems: TurnItem[] = [];

    for (const msg of messages) {
      if (msg.session_id !== sessionId) continue;
      if (msg.role !== 'user') continue;
      // 段切换 marker / 工具回显等非普通用户输入不算轮次起点
      if (msg.subtype) continue;
      if (!msg.content) continue;

      turnItems.push({
        index: turnItems.length + 1,
        messageId: msg.id,
        preview: toPreview(msg.content),
      });
    }

    return turnItems;
  }, [messages, sessionId]);

  return { items };
}
