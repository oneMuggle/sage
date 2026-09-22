/**
 * 任务控制台 (2026-09-19, P5)
 *
 * 注册 / 抽卡任务共用的监控面板：
 * - 状态行：snapshot（status / ok / failed / total）
 * - 日志流：GET events?after_seq=N 增量轮询（NDJSON 批量回放端点，
 *   after_seq 游标保证断连/刷新后续传不丢事件）
 * - 停止按钮；注册任务提供导出（register_results 文本另存）
 *
 * 终态（done/failed/stopped）后停止轮询并回调 onFinished。
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import {
  exportRegistrationJob,
  getDrawJob,
  getDrawJobEvents,
  getRegistrationJob,
  getRegistrationJobEvents,
  stopDrawJob,
  stopRegistrationJob,
  type ArenaJobEvent,
  type ArenaJobSnapshot,
} from '../../entities/arena';

const TERMINAL: ReadonlySet<string> = new Set(['done', 'failed', 'stopped']);
const MAX_LOG_LINES = 500;

interface JobConsoleProps {
  kind: 'register' | 'draw';
  jobId: string;
  pollIntervalMs?: number;
  onFinished?: (snapshot: ArenaJobSnapshot) => void;
}

export function JobConsole({ kind, jobId, pollIntervalMs = 2000, onFinished }: JobConsoleProps) {
  const [snapshot, setSnapshot] = useState<ArenaJobSnapshot | null>(null);
  const [events, setEvents] = useState<ArenaJobEvent[]>([]);
  const [error, setError] = useState('');
  const logRef = useRef<HTMLDivElement | null>(null);
  const finishedRef = useRef(false);
  const onFinishedRef = useRef(onFinished);
  onFinishedRef.current = onFinished;

  const getSnapshot = useCallback(
    () => (kind === 'draw' ? getDrawJob(jobId) : getRegistrationJob(jobId)),
    [kind, jobId],
  );
  const getEvents = useCallback(
    (afterSeq: number) =>
      kind === 'draw' ? getDrawJobEvents(jobId, afterSeq) : getRegistrationJobEvents(jobId, afterSeq),
    [kind, jobId],
  );
  const stopJob = useCallback(
    () => (kind === 'draw' ? stopDrawJob(jobId) : stopRegistrationJob(jobId)),
    [kind, jobId],
  );

  useEffect(() => {
    let cancelled = false;
    let lastSeq = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const tick = async () => {
      try {
        const [snap, newEvents] = await Promise.all([
          getSnapshot(),
          getEvents(lastSeq),
        ]);
        if (cancelled) return;
        setSnapshot(snap);
        if (newEvents.length > 0) {
          lastSeq = Math.max(lastSeq, ...newEvents.map((e) => e.seq));
          setEvents((prev) => [...prev, ...newEvents].slice(-MAX_LOG_LINES));
        }
        setError('');
        if (TERMINAL.has(snap.status)) {
          if (!finishedRef.current) {
            finishedRef.current = true;
            onFinishedRef.current?.(snap);
          }
          return; // 终态：停止轮询
        }
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
      }
      if (!cancelled) timer = setTimeout(() => void tick(), pollIntervalMs);
    };

    void tick();
    return () => {
      cancelled = true;
      if (timer !== null) clearTimeout(timer);
    };
  }, [getSnapshot, getEvents, pollIntervalMs]);

  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [events]);

  async function handleStop(): Promise<void> {
    try {
      await stopJob();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleExport(): Promise<void> {
    try {
      const text = await exportRegistrationJob(jobId);
      const blob = new Blob([text], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `register_results_${jobId}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const running = snapshot !== null && !TERMINAL.has(snapshot.status);

  return (
    <div className="rounded border border-border p-3 space-y-2" data-testid={`job-console-${jobId}`}>
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <p className="text-xs" data-testid="job-console-status">
          {snapshot
            ? `任务 ${snapshot.id} · ${snapshot.status} · 成功 ${snapshot.ok} / 失败 ${snapshot.failed} / 共 ${snapshot.total}`
            : `任务 ${jobId} · 加载中…`}
        </p>
        <div className="flex gap-2">
          {running && (
            <button
              type="button"
              onClick={() => void handleStop()}
              data-testid="job-console-stop"
              className="text-xs rounded border border-border px-2 py-1 hover:bg-bg-hover"
            >
              停止
            </button>
          )}
          {kind === 'register' && snapshot !== null && TERMINAL.has(snapshot.status) && (
            <button
              type="button"
              onClick={() => void handleExport()}
              data-testid="job-console-export"
              className="text-xs rounded border border-border px-2 py-1 hover:bg-bg-hover"
            >
              导出结果
            </button>
          )}
        </div>
      </div>
      {error && (
        <p className="text-xs text-error" data-testid="job-console-error" role="alert">
          {error}
        </p>
      )}
      <div
        ref={logRef}
        data-testid="job-console-log"
        className="h-56 overflow-y-auto rounded bg-bg-muted p-2 font-mono text-xs leading-5"
      >
        {events.length === 0 ? (
          <span className="text-text-muted">暂无事件…</span>
        ) : (
          events.map((event) => (
            <p
              key={event.seq}
              data-testid={`job-event-${event.seq}`}
              className={
                event.level === 'error'
                  ? 'text-error'
                  : event.level === 'warn'
                    ? 'text-amber-500'
                    : 'text-text'
              }
            >
              {`[${event.ts}] ${event.message}`}
            </p>
          ))
        )}
      </div>
    </div>
  );
}
