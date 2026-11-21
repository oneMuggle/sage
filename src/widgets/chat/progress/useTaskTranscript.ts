/**
 * M1: 任务 transcript 拉取与增量轮询。
 *
 * 子代理运行期间每 {@link POLL_INTERVAL_MS} 按 `after_seq` 增量拉取消息级
 * 过程记录（goal / reasoning / assistant / tool_call / tool_result / error），
 * 终态后停止轮询、保留已拉取内容。切换 run/task 时重置。
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import type { TaskTranscriptMessage } from '../../../shared/api/orchEvents';
import { orchRunControlClient } from '../../../shared/api/orchRunControlClient';

const POLL_INTERVAL_MS = 2_000;
const PAGE_SIZE = 200;
/** 单轮最多续页数（防止异常 has_more 造成无限循环）。 */
const MAX_PAGES_PER_SYNC = 5;

export interface UseTaskTranscriptOptions {
  runId: string;
  taskId: string;
  /** 是否加载（例如 Transcript tab 可见时才加载）。 */
  enabled: boolean;
  /** 任务仍在运行时开启轮询。 */
  live: boolean;
}

export interface UseTaskTranscriptResult {
  messages: TaskTranscriptMessage[];
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

export function useTaskTranscript({
  runId,
  taskId,
  enabled,
  live,
}: UseTaskTranscriptOptions): UseTaskTranscriptResult {
  const [messages, setMessages] = useState<TaskTranscriptMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nextSeqRef = useRef(0);
  const inflightRef = useRef(false);
  const generationRef = useRef(0);

  const sync = useCallback(
    async (reset: boolean) => {
      if (inflightRef.current) return;
      inflightRef.current = true;
      const generation = generationRef.current;
      if (reset) {
        nextSeqRef.current = 0;
        setMessages([]);
      }
      setLoading(true);
      try {
        let afterSeq = nextSeqRef.current;
        for (let page = 0; page < MAX_PAGES_PER_SYNC; page += 1) {
          const resp = await orchRunControlClient.getTaskTranscript(
            runId,
            taskId,
            afterSeq,
            PAGE_SIZE,
          );
          if (generationRef.current !== generation) return; // 已切换任务
          const batch = resp.messages ?? [];
          if (batch.length > 0) {
            setMessages((prev) => {
              const seen = new Set(prev.map((m) => m.seq));
              return [...prev, ...batch.filter((m) => !seen.has(m.seq))];
            });
            afterSeq = resp.next_seq;
            nextSeqRef.current = afterSeq;
          }
          if (!resp.has_more) break;
        }
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        inflightRef.current = false;
        if (generationRef.current === generation) setLoading(false);
      }
    },
    [runId, taskId],
  );

  // 切换任务时重置并首拉
  useEffect(() => {
    generationRef.current += 1;
    nextSeqRef.current = 0;
    setMessages([]);
    setError(null);
    if (enabled) void sync(true);
  }, [enabled, sync]);

  // 运行中增量轮询
  useEffect(() => {
    if (!enabled || !live) return undefined;
    const timer = setInterval(() => void sync(false), POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [enabled, live, sync]);

  const refresh = useCallback(() => {
    void sync(false);
  }, [sync]);

  return { messages, loading, error, refresh };
}
