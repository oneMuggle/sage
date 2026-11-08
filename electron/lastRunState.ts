/**
 * lastRunState — 启动时间线 / 异常退出判定（机器本地诊断状态）。
 *
 * 写入 ``<userData>/diagnostics/last-run.json``。下次启动读取上一次状态：
 * - stages 含 ``clean_exit`` → 正常退出；
 * - 否则（文件存在但无 clean_exit）→ 上次异常退出（应用内崩溃或被外部终止）；
 * - 文件不存在 / 损坏 → ``none``。
 *
 * 该模块**不依赖 Electron**，路径由调用方传入，便于单测与 CLI 共享 schema。
 */
import { appendFileSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';

export type RunEndStatus = 'clean' | 'unclean';

export interface LastRunState {
  schema: 1;
  bootId: string;
  appVersion: string;
  electron: string;
  startedAt: string;
  /** 启动时刻的 epoch ms；用于计算阶段相对偏移（跨时区/ISO 解析安全）。 */
  startedAtMs: number;
  stage: string;
  /** [stage, elapsedMs relative to startedAt] */
  stages: Array<[string, number]>;
  endedAt: string | null;
  endReason: string | null;
  safeModeLevel: number;
}

export interface CreateRunStateOptions {
  bootId: string;
  appVersion: string;
  electron: string;
  safeModeLevel: number;
  nowIso: string;
  nowMs: number;
}

export function createRunState(opts: CreateRunStateOptions): LastRunState {
  return {
    schema: 1,
    bootId: opts.bootId,
    appVersion: opts.appVersion,
    electron: opts.electron,
    startedAt: opts.nowIso,
    startedAtMs: opts.nowMs,
    stage: 'process_start',
    stages: [['process_start', 0]],
    endedAt: null,
    endReason: null,
    safeModeLevel: opts.safeModeLevel,
  };
}

/** 不可变追加阶段；同一阶段只记录第一次出现。 */
export function advanceStage(state: LastRunState, stage: string, nowMs: number): LastRunState {
  if (state.stages.some(([s]) => s === stage)) return state;
  const base =
    typeof state.startedAtMs === 'number' ? state.startedAtMs : Date.parse(state.startedAt);
  const offset = Number.isFinite(base) ? Math.max(0, nowMs - base) : 0;
  return {
    ...state,
    stage,
    stages: [...state.stages, [stage, offset]],
  };
}

export function markEnded(
  state: LastRunState,
  status: RunEndStatus,
  reason: string,
  nowIso: string,
): LastRunState {
  return {
    ...state,
    endedAt: nowIso,
    endReason: reason,
    stages: [
      ...state.stages,
      [status === 'clean' ? 'clean_exit' : 'unclean_exit', 0] as [string, number],
    ],
  };
}

export type PreviousRunKind = 'clean' | 'unclean' | 'none';

export function classifyPrevious(state: LastRunState | null): PreviousRunKind {
  if (!state) return 'none';
  if (state.stages.some(([s]) => s === 'clean_exit')) return 'clean';
  return 'unclean';
}

export function computeCrashStreak(previous: PreviousRunKind, currentStreak: number): number {
  if (previous === 'clean') return 0;
  if (previous === 'unclean') return currentStreak + 1;
  return currentStreak;
}

export function readLastRun(file: string): LastRunState | null {
  try {
    const raw = readFileSync(file, 'utf-8');
    const parsed = JSON.parse(raw) as Partial<LastRunState>;
    if (!parsed || parsed.schema !== 1 || typeof parsed.bootId !== 'string') return null;
    // fail-open 校验：损坏的 stages（null / 非数组 / 元素不可解构）会让
    // classifyPrevious 抛 TypeError 并炸掉 main.ts 模块加载，必须在这里拦住。
    if (!Array.isArray(parsed.stages)) return null;
    if (
      !parsed.stages.every(
        (entry) =>
          Array.isArray(entry) &&
          entry.length >= 2 &&
          typeof entry[0] === 'string' &&
          typeof entry[1] === 'number',
      )
    ) {
      return null;
    }
    // 兼容旧 schema：没有 startedAtMs 时回落到 startedAt 解析
    const state = parsed as LastRunState;
    if (typeof state.startedAtMs !== 'number') {
      const base = Date.parse(state.startedAt);
      state.startedAtMs = Number.isFinite(base) ? base : 0;
    }
    return state;
  } catch {
    return null;
  }
}

export function writeLastRun(file: string, state: LastRunState): void {
  mkdirSync(dirname(file), { recursive: true });
  const tmp = `${file}.tmp`;
  writeFileSync(tmp, JSON.stringify(state, null, 2), 'utf-8');
  renameSync(tmp, file);
}

/** 追加一条阶段事件到诊断日志（不依赖 last-run 主文件）。 */
export function appendBootEvent(file: string, stage: string, nowIso: string, meta?: unknown): void {
  try {
    mkdirSync(dirname(file), { recursive: true });
    appendFileSync(file, `${JSON.stringify({ ts: nowIso, stage, meta })}\n`, 'utf-8');
  } catch {
    // 诊断是增强能力，不能反过来影响启动
  }
}
