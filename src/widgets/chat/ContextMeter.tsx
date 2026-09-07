// src/widgets/chat/ContextMeter.tsx
//
// U17 上下文用量指示 (对标增强第四轮批次 B, docs/plans/2026-09-07_coding-agent-parity-round4.md):
// 当前会话的模型上下文窗口占用率。数据源: GET /api/v1/usage/session/{id} 的
// last_prompt_tokens(上一轮请求 prompt = 当前上下文占用的最佳代理) +
// last_model(经 modelWindows 最长前缀映射出窗口大小)。
// 刷新时机: 流结束跳变(后台会话跑完也刷新) + 60s 兜底轮询 + 外部 refreshKey。

import { useEffect, useRef, useState } from 'react';

import { useChatStreamStore, selectSessionSlots } from '../../features/send-message/chatStreamStore';
import { fetchSessionUsage, type SessionUsage } from '../../shared/api/usageApi';
import { contextWindowFor } from '../../shared/lib/modelWindows';

function formatTokens(total: number): string {
  if (total >= 1_000_000) return `${(total / 1_000_000).toFixed(1)}M`;
  if (total >= 1_000) return `${(total / 1_000).toFixed(1)}k`;
  return String(total);
}

/** 占用率 → 颜色档位: <70% 常态, 70-90% 注意, ≥90% 临近压缩/截断 */
function toneClass(pct: number): { bar: string; text: string } {
  if (pct >= 0.9) return { bar: 'bg-red-500', text: 'text-red-500' };
  if (pct >= 0.7) return { bar: 'bg-amber-500', text: 'text-amber-500' };
  return { bar: 'bg-accent', text: 'text-text-secondary' };
}

interface ContextMeterProps {
  sessionId: string | null;
  /** 外部可触发刷新 (例如流结束后) */
  refreshKey?: number;
}

export function ContextMeter({ sessionId, refreshKey = 0 }: ContextMeterProps) {
  const [usage, setUsage] = useState<SessionUsage | null>(null);
  // 流结束跳变检测: 本会话 streaming.messageId 非空 → null 时刷新用量
  const streamingMessageId = useChatStreamStore((s) =>
    selectSessionSlots(s, sessionId).streaming?.messageId ?? null,
  );
  const prevStreamingIdRef = useRef<string | null>(null);

  const load = (sid: string | null): void => {
    if (!sid) {
      setUsage(null);
      return;
    }
    fetchSessionUsage(sid)
      .then((u) => setUsage(u))
      .catch(() => {
        /* 静默: 指示器是增强信息 */
      });
  };

  useEffect(() => {
    load(sessionId);
    if (!sessionId) return;
    const timer = window.setInterval(() => load(sessionId), 60_000);
    return () => window.clearInterval(timer);
  }, [sessionId, refreshKey]);

  useEffect(() => {
    const prev = prevStreamingIdRef.current;
    prevStreamingIdRef.current = streamingMessageId;
    if (prev !== null && streamingMessageId === null && sessionId) {
      load(sessionId);
    }
  }, [streamingMessageId, sessionId]);

  if (!sessionId || !usage || usage.last_prompt_tokens == null) return null;

  const windowTokens = contextWindowFor(usage.last_model);
  const used = usage.last_prompt_tokens;
  const pct = windowTokens > 0 ? Math.min(1, used / windowTokens) : 0;
  const { bar, text } = toneClass(pct);
  const cached = usage.last_cached_tokens ?? 0;
  const title = [
    `上下文约 ${formatTokens(used)} / ${formatTokens(windowTokens)} tokens (${Math.round(pct * 100)}%)`,
    usage.last_model ? `模型: ${usage.last_model}` : null,
    cached > 0 ? `其中缓存命中 ${formatTokens(cached)}` : null,
    '达到阈值后会自动压缩历史',
  ]
    .filter(Boolean)
    .join('\n');

  return (
    <span
      className="flex items-center gap-1.5 text-[11px] text-text-secondary shrink-0"
      title={title}
      data-testid="context-meter"
    >
      <span className="relative h-1.5 w-16 overflow-hidden rounded-full bg-bg-muted">
        <span
          className={`absolute inset-y-0 left-0 rounded-full ${bar}`}
          style={{ width: `${Math.max(2, Math.round(pct * 100))}%` }}
        />
      </span>
      <span className={pct >= 0.9 ? text : undefined}>{Math.round(pct * 100)}%</span>
    </span>
  );
}
