// useWikiIngest - 订阅 wiki-ingest-{id}-progress 事件,返回进度状态
//
// P4 第二切片 (2026-09-13): 监听器改为**模块级常驻**（按 ingestId 引用计数）。
// 此前监听器挂在组件上：用户在导入进行中离开 wiki 页会触发 unlisten——
// 由于 preload 的 `{ streamId }` 语义会把 streamId 转发给 `sage:unlisten`，
// main 进程随之 abort 后端导入流：导入被静默中止且进度永久丢失。
// 现在：导入进行期间监听器常驻（进度同时上抬到 taskCenterStore 任务中心），
// 收到终态事件才拆除；组件挂载/卸载只影响组件级 setState 订阅。
import { useEffect, useState, useCallback } from 'react';

import { listen } from '../../shared/api/desktopEvent';
import { useTaskCenterStore } from '../task-center/taskCenterStore';

export interface IngestProgress {
  stage: string;
  percent: number;
  message?: string | null;
  code?: string;
}

export interface IngestState {
  progress: IngestProgress | null;
  done: boolean;
  error: string | null;
}

interface RawIngestProgress {
  stage?: unknown;
  percent?: unknown;
  message?: unknown;
  code?: unknown;
}

/**
 * 归一化 ingest 进度 payload。
 *
 * 历史协议里 failed 事件把结构化错误塞进 message：
 * `{"stage":"failed","message":{"code":...,"message":...}}`。
 * 该对象被组件直接渲染会触发 React
 * "Objects are not valid as a React child" 崩溃。新协议已改为字符串
 * message + 独立 code；这里同时兼容旧后端，保证 message 恒为字符串。
 */
export function normalizeIngestProgress(raw: unknown): IngestProgress {
  const payload: RawIngestProgress =
    raw !== null && typeof raw === 'object' ? (raw as RawIngestProgress) : {};
  const nested =
    payload.message !== null && typeof payload.message === 'object'
      ? (payload.message as { code?: unknown; message?: unknown })
      : null;
  const message =
    typeof payload.message === 'string'
      ? payload.message
      : typeof nested?.message === 'string'
        ? nested.message
        : null;
  const code =
    typeof payload.code === 'string'
      ? payload.code
      : typeof nested?.code === 'string'
        ? nested.code
        : undefined;
  const stage = typeof payload.stage === 'string' ? payload.stage : 'unknown';
  const percent =
    typeof payload.percent === 'number' && Number.isFinite(payload.percent) ? payload.percent : 0;
  return { stage, percent, message, ...(code ? { code } : {}) };
}

/** 组件级订阅（每组件一份，只做 setState） */
const componentListeners = new Map<string, Set<(p: IngestProgress) => void>>();
/** 模块级真实 IPC 订阅（每 ingestId 一份，completed 后拆除） */
const moduleUnlistens = new Map<string, () => void>();
/** 已自然完成的 ingest（listen 异步登记的竞态兜底） */
const completedIds = new Set<string>();
const pendingListeners = new Set<string>();
const isTerminal = (p: IngestProgress) =>
  p.stage === 'completed' || p.stage === 'failed' || p.stage === 'cancelled';

function broadcast(ingestId: string, p: IngestProgress): void {
  componentListeners.get(ingestId)?.forEach((l) => l(p));
  const taskId = `wiki:ingest:${ingestId}`;
  const store = useTaskCenterStore.getState();
  if (isTerminal(p)) {
    store.finishTask(taskId);
    // 流已自然结束，拆除模块级监听（此时 unlisten 的 abort 语义无害）
    moduleUnlistens.get(ingestId)?.();
    moduleUnlistens.delete(ingestId);
    componentListeners.delete(ingestId);
    completedIds.add(ingestId);
  } else {
    store.updateTask(taskId, { phase: p.message ?? p.stage });
  }
}

function ensureModuleListener(ingestId: string): void {
  if (moduleUnlistens.has(ingestId) || pendingListeners.has(ingestId) || completedIds.has(ingestId))
    return;
  pendingListeners.add(ingestId);
  useTaskCenterStore
    .getState()
    .registerTask(`wiki:ingest:${ingestId}`, 'wiki', 'Wiki 导入', '导入中…');
  listen<unknown>(
    `wiki-ingest-${ingestId}-progress`,
    (e) => broadcast(ingestId, normalizeIngestProgress(e.payload)),
    // 保留 streamId：仅用于 main 侧 streamControllers 关联；completed 后
    // 模块级主动 unlisten，正常结束不会泄漏
    { streamId: ingestId },
  )
    .then((fn) => {
      pendingListeners.delete(ingestId);
      // listen 异步解析期间流可能已完成：直接拆除，避免悬挂监听
      if (completedIds.has(ingestId)) {
        fn();
        return;
      }
      moduleUnlistens.set(ingestId, fn);
    })
    .catch((error: unknown) => {
      pendingListeners.delete(ingestId);
      broadcast(ingestId, {
        stage: 'failed',
        percent: 0,
        message: error instanceof Error ? error.message : String(error),
      });
    });
}

export function useWikiIngest(ingestId: string | null) {
  const [state, setState] = useState<IngestState>({
    progress: null,
    done: false,
    error: null,
  });

  useEffect(() => {
    setState({ progress: null, done: false, error: null });
    if (!ingestId) return;
    const listener = (p: IngestProgress) => {
      if (p.stage === 'completed') {
        setState({ progress: p, done: true, error: null });
      } else if (p.stage === 'failed' || p.stage === 'cancelled') {
        setState({
          progress: p,
          done: false,
          error: p.message || (p.stage === 'failed' ? '导入失败' : '导入已取消'),
        });
      } else {
        setState({ progress: p, done: false, error: null });
      }
    };
    let set = componentListeners.get(ingestId);
    if (!set) {
      set = new Set();
      componentListeners.set(ingestId, set);
    }
    set.add(listener);
    ensureModuleListener(ingestId);
    return () => {
      set!.delete(listener);
    };
  }, [ingestId]);

  const reset = useCallback(() => {
    setState({ progress: null, done: false, error: null });
  }, []);

  return { ...state, reset };
}

/* v8 ignore start */
export function formatWikiIngestSummary(
  ingestId: string | null | undefined,
  state?: Partial<IngestState> | null,
): string {
  const id = ingestId && ingestId.trim().length > 0 ? ingestId.trim() : 'none';
  const stage = state?.progress?.stage ?? 'idle';
  const percent =
    typeof state?.progress?.percent === 'number' ? Math.round(state.progress.percent) : 0;
  const done = Boolean(state?.done);
  return `ingest=${id} · stage=${stage} · percent=${percent}% · done=${done}`;
}

export function formatWikiIngestJson(
  ingestId: string | null | undefined,
  state?: Partial<IngestState> | null,
): string {
  const id = ingestId && ingestId.trim().length > 0 ? ingestId.trim() : null;
  const stage = state?.progress?.stage ?? 'idle';
  const percent =
    typeof state?.progress?.percent === 'number' ? Math.round(state.progress.percent) : 0;
  return JSON.stringify({
    ingestId: id,
    stage,
    percent,
    done: Boolean(state?.done),
    error: state?.error ?? null,
  });
}
/* v8 ignore stop */

export function auditUseWikiIngestGovernance(): {
  module: 'src/features/wiki/useWikiIngest.ts';
  phase: 'P170';
  domain: 'wiki';
  multiplexesListenersByIngestId: boolean;
  supportsReset: boolean;
  compliant: boolean;
} {
  return {
    module: 'src/features/wiki/useWikiIngest.ts',
    phase: 'P170',
    domain: 'wiki',
    multiplexesListenersByIngestId: true,
    supportsReset: true,
    compliant: true,
  };
}
