// src/widgets/chat/hooks/useSessionUsage.ts
//
// 2026-11-25: 会话用量的统一取数层（composer 状态条下沉配套）。
//
// 下沉之前 SessionUsageBadge 与 ContextMeter 各自调用 fetchSessionUsage：
//   - P3 同一个会话、同一个接口被请求两次，轮询周期也各自为政
//   - P4 只有 ContextMeter 在流结束时刷新，用量/延迟数字滞后一轮
// 本 hook 把取数收敛到一处：单次请求 + 仅流式期间轮询 + 流末立即刷新，
// 请求失败静默（状态条是增强信息，不应打断输入）。

import { useCallback, useEffect, useRef, useState } from 'react';

import {
  selectSessionSlots,
  useChatStreamStore,
} from '../../../features/send-message/chatStreamStore';
import { fetchSessionUsage, type SessionUsage } from '../../../shared/api/usageApi';

/** 流式进行中的兜底轮询周期 (ms)。空闲会话不做无效刷新。 */
const POLL_INTERVAL_MS = 60_000;

export interface UseSessionUsageResult {
  /** 最近一次成功取到的会话用量快照；null 表示尚未取到或已清空。 */
  usage: SessionUsage | null;
  /** true 表示正在取数（usage 尚为 null）。 */
  isLoading: boolean;
}

/**
 * 拉取并维护单个会话的用量快照。
 *
 * - sessionId 变化 → 立即拉取（切换会话先清空，避免显示上一会话的数字）
 * - 流式进行中 → 60s 轮询
 * - 流式结束（streaming.messageId 由非空变 null）→ 立即拉取
 * - 请求失败 → 静默，保留上一次的值
 */
export function useSessionUsage(sessionId: string | null): UseSessionUsageResult {
  const [usage, setUsage] = useState<SessionUsage | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  // 流结束跳变检测：本会话 streaming.messageId 非空 → null 即一轮回复收尾。
  const streamingMessageId = useChatStreamStore(
    (s) => selectSessionSlots(s, sessionId).streaming?.messageId ?? null,
  );
  const isStreaming = streamingMessageId !== null;

  // 请求序号：只有最后一次请求的结果可以落地，避免旧会话的在途响应覆盖新会话。
  const requestSeqRef = useRef(0);

  const load = useCallback((): void => {
    if (!sessionId) return;
    const seq = ++requestSeqRef.current;
    setIsLoading(true);
    fetchSessionUsage(sessionId)
      .then((u) => {
        if (seq !== requestSeqRef.current) return;
        setUsage(u);
        setIsLoading(false);
      })
      .catch(() => {
        // 静默: 状态条是增强信息，拉取失败不打断输入，也不抛错。
        if (seq !== requestSeqRef.current) return;
        setIsLoading(false);
      });
  }, [sessionId]);

  // 会话切换：先作废在途请求并清空旧值，再拉新会话。
  useEffect(() => {
    if (!sessionId) {
      requestSeqRef.current += 1;
      setUsage(null);
      setIsLoading(false);
      return;
    }
    setUsage(null);
    load();
  }, [sessionId, load]);

  // 仅流式进行中才轮询（60s 兜底，覆盖长回答期间的累计量）。
  useEffect(() => {
    if (!sessionId || !isStreaming) return;
    const timer = window.setInterval(load, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [sessionId, isStreaming, load]);

  // 流结束立即刷新：最后一轮的 token/成本/延迟只有在这一刻才是准确值。
  const prevStreamingIdRef = useRef<string | null>(null);
  useEffect(() => {
    const prev = prevStreamingIdRef.current;
    prevStreamingIdRef.current = streamingMessageId;
    if (prev !== null && streamingMessageId === null) load();
  }, [streamingMessageId, load]);

  return { usage, isLoading };
}
