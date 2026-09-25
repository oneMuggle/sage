// src/features/chat/useQuoteDraft.ts
//
// 对话阅读导航 A4/A5（docs/mcp-chat-reading-nav-optimization.md）：
// 引用注入通道 —— 整条引用与划词引用都转成 Markdown 引用块，以
// mode='append' 交给 ChatInput 追加到草稿尾部（不覆盖已输入内容）。
//
// 注入是一次性事件：输入框消费后下一帧清空。否则编辑重发结束时
// `injectedDraft` 会回落到旧引用，在追加语义下重复追加。

import { useCallback, useEffect, useState } from 'react';

import { formatQuoteBlock } from './selectionQuote';

export interface QuoteDraftInjection {
  text: string;
  nonce: number;
  mode: 'append';
}

export function useQuoteDraft(): {
  quotedDraft: QuoteDraftInjection | null;
  quoteText: (text: string) => void;
} {
  const [quotedDraft, setQuotedDraft] = useState<QuoteDraftInjection | null>(null);

  useEffect(() => {
    if (!quotedDraft) return;
    const frame = requestAnimationFrame(() => setQuotedDraft(null));
    return () => cancelAnimationFrame(frame);
  }, [quotedDraft]);

  const quoteText = useCallback((text: string) => {
    setQuotedDraft({ text: formatQuoteBlock(text), nonce: Date.now(), mode: 'append' });
  }, []);

  return { quotedDraft, quoteText };
}
