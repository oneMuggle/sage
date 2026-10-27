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
  mode: 'append' | 'replace';
}

export function useQuoteDraft(): {
  quotedDraft: QuoteDraftInjection | null;
  quoteText: (text: string) => void;
  setDraftText: (text: string) => void;
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

  /** 直接把输入框内容替换为指定文本（编辑队列消息时使用）。 */
  const setDraftText = useCallback((text: string) => {
    setQuotedDraft({ text, nonce: Date.now(), mode: 'replace' });
  }, []);

  return { quotedDraft, quoteText, setDraftText };
}

export function formatQuoteDraftInjectionSummary(draft: QuoteDraftInjection | null): string {
  if (!draft) return 'idle';
  return `${draft.mode} · ${draft.text.length} chars · nonce=${draft.nonce}`;
}

export function formatQuoteDraftInjectionJson(draft: QuoteDraftInjection | null): string {
  return JSON.stringify(
    {
      active: draft !== null,
      mode: draft?.mode ?? null,
      textLength: draft?.text.length ?? 0,
      nonce: draft?.nonce ?? null,
      text: draft?.text ?? null,
    },
    null,
    2,
  );
}

export interface UseQuoteDraftGovernanceAudit {
  phase: 'P161';
  module: 'src/features/chat/useQuoteDraft.ts';
  archetype: string;
  sessionId: string;
  healthy: boolean;
  summaryMarkdown: string;
}

export function auditUseQuoteDraftGovernance(
  sessionId = 'default',
  archetype = 'software-engineering',
): UseQuoteDraftGovernanceAudit {
  const normalizedSession = sessionId.trim() || 'default';
  const normalizedArchetype = archetype.trim() || 'software-engineering';
  return {
    phase: 'P161',
    module: 'src/features/chat/useQuoteDraft.ts',
    archetype: normalizedArchetype,
    sessionId: normalizedSession,
    healthy: normalizedSession.length > 0 && normalizedArchetype.length > 0,
    summaryMarkdown: `### P161 UseQuoteDraft Governance\n- session: ${normalizedSession}\n- archetype: ${normalizedArchetype}`,
  };
}
