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
  /** B3 / B4：定位后高亮的检索词（不区分大小写的字面匹配） */
  highlightQuery?: string;
  /**
   * B4 会话内查找：突出目标消息内第几处命中（0 起）并滚动到该处，不闪烁整条消息。
   * 缺省为 B3 搜索命中模式：高亮全部命中，数秒后自动清除。
   */
  highlightIndex?: number;
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

export interface MessageJumpStoreAuditSnapshot {
  hasPending: boolean;
  messageId: string | null;
  nonce: number | null;
  hasHeadingHint: boolean;
  hasHighlightQuery: boolean;
  highlightIndex: number | null;
  ttlMs: number;
  signature: string;
}

export function buildMessageJumpStoreAuditSnapshot(
  pending: MessageJumpRequest | null = useMessageJumpStore.getState().pending,
): MessageJumpStoreAuditSnapshot {
  const req = pending ?? null;
  const hasPending = req !== null;
  const messageId = req?.messageId ?? null;
  const nonce = typeof req?.nonce === 'number' ? req.nonce : null;
  const hasHeadingHint = Boolean(
    (typeof req?.headingText === 'string' && req.headingText.trim().length > 0) ||
      typeof req?.headingIndex === 'number',
  );
  const hasHighlightQuery = Boolean(
    typeof req?.highlightQuery === 'string' && req.highlightQuery.trim().length > 0,
  );
  const highlightIndex = typeof req?.highlightIndex === 'number' ? req.highlightIndex : null;
  const ttlMs = MESSAGE_JUMP_TTL_MS;
  const signature = `${hasPending ? 1 : 0}|${messageId ?? '-'}|${nonce ?? -1}|${hasHeadingHint ? 1 : 0}|${hasHighlightQuery ? 1 : 0}|${highlightIndex ?? -1}|${ttlMs}`;
  return {
    hasPending,
    messageId,
    nonce,
    hasHeadingHint,
    hasHighlightQuery,
    highlightIndex,
    ttlMs,
    signature,
  };
}

export function buildMessageJumpStoreAuditJson(
  pending: MessageJumpRequest | null = useMessageJumpStore.getState().pending,
): string {
  return JSON.stringify(buildMessageJumpStoreAuditSnapshot(pending), null, 2);
}
