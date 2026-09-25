// src/features/chat/messageJumpStore.ts
//
// 对话阅读导航 A1（docs/mcp-chat-reading-nav-optimization.md）：
// "定位到某条消息"的全局请求通道。
//
// 发起方（对话大纲、侧栏搜索命中……）只登记 messageId；真正的滚动由
// MessageList 在目标消息出现在列表中时消费（会话切换后消息是异步加载的，
// 所以请求需要能"等"）。消息 ID 全局唯一，请求不必携带 sessionId ——
// 只有目标所在会话的列表能消费它。超过 TTL 仍未消费（消息已删除、加载失败）
// 则静默过期，不会在之后某次无关渲染里突然跳走。

import { create } from 'zustand';

/** 定位请求的存活时间：覆盖会话切换 + 消息加载的常见耗时 */
export const MESSAGE_JUMP_TTL_MS = 8000;

export interface MessageJumpRequest {
  /** 目标消息 ID */
  messageId: string;
  /** 大纲定位：目标标题的 Markdown 原文（比较前去掉行内标记） */
  headingText?: string;
  /** 大纲定位兜底：该消息内第几个 h2/h3（0 起） */
  headingIndex?: number;
  /** 每次请求唯一；重复点击同一目标也会重新定位 */
  nonce: number;
}

export type MessageJumpInput = Omit<MessageJumpRequest, 'nonce'>;

interface MessageJumpState {
  pending: MessageJumpRequest | null;
  request: (input: MessageJumpInput) => number;
  consume: (nonce: number) => void;
}

let nonceSeq = 0;

export const useMessageJumpStore = create<MessageJumpState>((set, get) => ({
  pending: null,
  request: (input) => {
    nonceSeq += 1;
    const nonce = nonceSeq;
    set({ pending: { ...input, nonce } });
    setTimeout(() => {
      if (get().pending?.nonce === nonce) set({ pending: null });
    }, MESSAGE_JUMP_TTL_MS);
    return nonce;
  },
  consume: (nonce) => {
    if (get().pending?.nonce === nonce) set({ pending: null });
  },
}));

/** 便捷入口：登记一次定位请求，返回其 nonce */
export function requestMessageJump(input: MessageJumpInput): number {
  return useMessageJumpStore.getState().request(input);
}
