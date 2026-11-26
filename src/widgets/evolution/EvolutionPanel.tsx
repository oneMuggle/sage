/**
 * EvolutionPanel - 进化系统面板
 *
 * 2026-11-26：手动维护任务的运行态改由 evolutionRunStore 持有。
 * 此前 running 状态存在组件本地 useState，设置页切 tab / 跳去会话页
 * 会卸载组件、状态归零 —— 而后端任务还在跑，UI 与任务失联且可重复触发。
 * 现在轮询活在 store 层，任何页面重新挂载都会恢复到「执行中 + 当前阶段」。
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useEvolutionRunStore } from '../../entities/evolution/evolutionRunStore';
import { invoke } from '../../shared/api/desktopInvoke';
import type { EvolutionRunSnapshot } from '../../shared/api/types/domainEntityTypes';
import { formatLocalString } from '../../shared/lib/timeFormatter';

interface EvolutionLog {
  id: string;
  evolution_type: string;
  description: string;
  status: string;
  created_at: number;
  completed_at?: number | null;
}

const TASK_DISPLAY: Record<string, string> = {
  daily_summary: '每日摘要',
  memory_pruning: '记忆修剪',
  preference_learning: '偏好学习',
  importance_reevaluation: '重要性重评估',
  // 本任务只做“晋升 + 重要度衰减”，不合并重复事实
  memory_consolidation: '记忆固化（晋升/衰减）',
  memory_reflection: '记忆反思（去重/合并）',
  skill_consolidation: '技能巡检',
  maintenance_catchup: '进化补跑',
};

const RUNNABLE_TASKS: Array<{
  name: string;
  label: string;
  description: string;
}> = [
  {
    name: 'memory_reflection',
    label: '立即整理记忆',
    description: '扫描近 7 天 + 滚动存量，去重/合并/失效',
  },
  {
    name: 'memory_pruning',
    label: '立即修剪',
    description: '清理过期、低价值与低质量长期未用记忆',
  },
  {
    name: 'memory_consolidation',
    label: '立即固化',
    description: '高频情景记忆晋升语义层并衰减冷记忆重要度',
  },
];

/** 记忆反思的阶段清单 —— 与后端 MemoryReflectionTask 上报的 phase 键对齐。 */
const REFLECTION_PHASES: Array<{ key: string; label: string }> = [
  { key: 'collect', label: '扫描记忆' },
  { key: 'group', label: '分组' },
  { key: 'dedupe', label: '去重' },
  { key: 'llm', label: 'LLM 合并' },
  { key: 'finalize', label: '写入结果' },
];

const STATUS_DISPLAY: Record<string, { label: string; className: string }> = {
  success: { label: '成功', className: 'text-success' },
  failed: { label: '失败', className: 'text-danger' },
  skipped: { label: '跳过', className: 'text-warning' },
  skipped_no_llm: { label: '跳过（无 LLM）', className: 'text-warning' },
};

/** 把任务统计渲染成一行摘要；游标是内部实现细节，不展示给用户。 */
// eslint-disable-next-line react-refresh/only-export-components
export function formatEvolutionRunResult(
  result: Record<string, unknown> | null | undefined,
): string | null {
  if (!result) return null;
  const parts = Object.entries(result)
    .filter(([key]) => key !== 'reflection_backlog_cursor_ms')
    .map(([key, value]) => `${key}: ${String(value)}`);
  return parts.length > 0 ? parts.join('，') : null;
}

function formatElapsed(startedAt: number | null, nowMs: number): string {
  if (!startedAt) return '';
  const seconds = Math.max(0, Math.floor((nowMs - startedAt) / 1000));
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return minutes > 0 ? `${minutes}m${rest}s` : `${rest}s`;
}

/** 运行中每秒刷新一次的时钟（只用于已耗时显示，不参与快照轮询）。 */
function useNowTicker(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return undefined;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);
  return now;
}

const RunningProgress: React.FC<{ run: EvolutionRunSnapshot; onCancel: () => void }> = ({
  run,
  onCancel,
}) => {
  const now = useNowTicker(true);
  const currentIndex = REFLECTION_PHASES.findIndex((phase) => phase.key === run.phase);
  const isReflection = currentIndex >= 0;
  const llmDone = Number(run.progress.llm_done);
  const llmTotal = Number(run.progress.llm_total);
  const scanned = Number(run.progress.scanned);

  return (
    <div
      data-testid="evolution-run-progress"
      className="mt-3 rounded-radius-sm border border-border bg-surface px-3 py-2 text-xs"
    >
      <div className="flex items-center justify-between">
        <span className="text-text-secondary">
          <span className="mr-1.5 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
          {TASK_DISPLAY[run.name] ?? run.name}执行中 · {run.phase_label ?? '准备中'}
        </span>
        <span className="flex items-center gap-2 text-muted">
          {formatElapsed(run.started_at, now)}
          <button
            type="button"
            data-testid="evolution-run-cancel"
            onClick={onCancel}
            disabled={run.cancel_requested}
            title="协作式取消：任务在当前阶段结束后的检查点停止"
            className="rounded-radius-sm border border-border px-2 py-0.5 text-ui-2xs text-text-secondary hover:bg-bg-hover disabled:opacity-50"
          >
            {run.cancel_requested ? '取消中…' : '取消'}
          </button>
        </span>
      </div>
      {isReflection && (
        <ol className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-muted">
          {REFLECTION_PHASES.map((phase, index) => {
            const state =
              index < currentIndex ? 'done' : index === currentIndex ? 'current' : 'pending';
            const suffix =
              state === 'current' && phase.key === 'llm' && llmTotal > 0
                ? ` ${Math.max(0, Math.min(llmDone, llmTotal))}/${llmTotal}`
                : '';
            return (
              <li
                key={phase.key}
                data-phase-state={state}
                className={
                  state === 'done'
                    ? 'text-success'
                    : state === 'current'
                      ? 'font-medium text-primary'
                      : ''
                }
              >
                {state === 'done' ? '✓ ' : ''}
                {phase.label}
                {suffix}
              </li>
            );
          })}
        </ol>
      )}
      {!isReflection && scanned > 0 && <p className="mt-1.5 text-muted">已扫描 {scanned} 条记忆</p>}
    </div>
  );
};

export const EvolutionPanel: React.FC = () => {
  const [logs, setLogs] = useState<EvolutionLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [triggerError, setTriggerError] = useState<string | null>(null);
  const runs = useEvolutionRunStore((state) => state.runs);
  const refreshRuns = useEvolutionRunStore((state) => state.refresh);
  const triggerRun = useEvolutionRunStore((state) => state.trigger);
  const cancelRun = useEvolutionRunStore((state) => state.cancel);

  const fetchLogs = useCallback(async () => {
    try {
      setError(null);
      const result = await invoke<EvolutionLog[]>('get_evolution_logs', {
        limit: 10,
        offset: 0,
      });
      setLogs(Array.isArray(result) ? result : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchLogs();
    // 重入恢复：上一轮/其他入口触发的任务可能仍在跑，进面板先取一次快照
    void refreshRuns();
    const interval = setInterval(fetchLogs, 60_000);
    return () => clearInterval(interval);
  }, [fetchLogs, refreshRuns]);

  const runningEntry = useMemo(
    () => Object.values(runs).find((run) => run.state === 'running') ?? null,
    [runs],
  );

  // 任务刚结束：立即刷新最近执行记录，不再等 60s 轮询
  const wasRunningRef = useRef(false);
  useEffect(() => {
    const isRunning = runningEntry !== null;
    if (wasRunningRef.current && !isRunning) {
      void fetchLogs();
    }
    wasRunningRef.current = isRunning;
  }, [runningEntry, fetchLogs]);

  const latestFinished = useMemo(() => {
    const finished = Object.values(runs).filter((run) => run.state !== 'running');
    finished.sort((a, b) => (b.finished_at ?? 0) - (a.finished_at ?? 0));
    return finished[0] ?? null;
  }, [runs]);

  const runTask = async (name: string): Promise<void> => {
    setTriggerError(null);
    try {
      await triggerRun(name);
    } catch (err) {
      setTriggerError(err instanceof Error ? err.message : String(err));
    }
  };

  const cancelTask = async (name: string): Promise<void> => {
    setTriggerError(null);
    try {
      await cancelRun(name);
    } catch (err) {
      setTriggerError(err instanceof Error ? err.message : String(err));
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8">
        <div className="text-muted">加载中...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 p-8">
        <div className="text-sm text-danger">加载进化日志失败：{error}</div>
        <button
          onClick={() => void fetchLogs()}
          className="text-sm text-primary hover:text-primary-hover"
        >
          重试
        </button>
      </div>
    );
  }

  const finishedSummary = latestFinished ? formatEvolutionRunResult(latestFinished.result) : null;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-text">进化系统</h2>
        {/* P2-7: 原文案「已由后台自动调度,无需手动操作」只覆盖了维护任务,
            却挂在「进化系统」标题下 —— 用户会推断「凡属自演化都不需要我管」,
            这与技能演化实际需要人审批（草稿 approve/reject）直接矛盾,
            也与 PHILOSOPHY 的「透明可控」相悖。改为如实分两层陈述。 */}
        <p className="text-sm text-muted mt-1">
          5 个维护任务由后台自动调度(SchedulerService cron 触发),无需手动干预: 每日摘要 / 记忆修剪 /
          偏好学习 / 重要性重评估 / 记忆合并。
        </p>
        <p className="text-sm text-muted mt-1">
          但技能演化不一样 —— 它只产出草稿,不会自行改动你的技能。
          草稿需在「技能」页逐条预览后批准或拒绝,批准前不影响现有行为。
        </p>
      </div>

      <div>
        <h3 className="text-sm font-medium text-text-secondary mb-3">维护操作</h3>
        <p className="text-xs text-muted mb-2">
          应用关闭会错过凌晨的自动任务；这里可手动补跑。重度任务会调用模型，建议空闲时执行。
          运行在后台进行，切换页面不会中断，回来仍可看到进度。
        </p>
        <div className="flex flex-wrap gap-2">
          {RUNNABLE_TASKS.map((task) => {
            const taskRun = runs[task.name];
            const isRunning = taskRun?.state === 'running';
            return (
              <button
                key={task.name}
                type="button"
                disabled={runningEntry !== null}
                onClick={() => void runTask(task.name)}
                title={task.description}
                data-testid={`evolution-run-${task.name}`}
                className="px-3 py-1.5 text-xs rounded-radius-sm border border-border text-text hover:bg-bg-hover disabled:opacity-50"
              >
                {isRunning ? `整理中 · ${taskRun.phase_label ?? '执行中'}` : task.label}
              </button>
            );
          })}
        </div>
        {runningEntry && (
          <RunningProgress run={runningEntry} onCancel={() => void cancelTask(runningEntry.name)} />
        )}
        {triggerError && (
          <p className="text-xs text-danger mt-2" data-testid="evolution-run-error">
            启动失败：{triggerError}
          </p>
        )}
        {latestFinished && (
          <p className="text-xs text-text-secondary mt-2" data-testid="evolution-run-result">
            {TASK_DISPLAY[latestFinished.name] ?? latestFinished.name}
            {latestFinished.state === 'succeeded'
              ? `完成${finishedSummary ? `：${finishedSummary}` : ''}`
              : latestFinished.state === 'cancelled'
                ? '已取消'
                : `失败：${latestFinished.error ?? '未知错误'}`}
          </p>
        )}
      </div>

      <div>
        <h3 className="text-sm font-medium text-text-secondary mb-3">最近执行记录</h3>
        {logs.length === 0 ? (
          <div className="text-center py-8 text-muted">暂无进化日志</div>
        ) : (
          <ul className="space-y-2">
            {logs.map((log) => (
              <li
                key={log.id}
                className="bg-surface rounded-lg shadow p-3 border border-border text-sm"
              >
                <div className="flex justify-between">
                  <span className="font-medium text-text">
                    {TASK_DISPLAY[log.evolution_type] || log.evolution_type}
                  </span>
                  <span
                    className={
                      STATUS_DISPLAY[log.status]?.className ?? 'text-text-secondary bg-bg-subtle'
                    }
                  >
                    {STATUS_DISPLAY[log.status]?.label ?? log.status}
                  </span>
                </div>
                <p className="text-xs text-muted mt-1">{log.description}</p>
                <p className="text-xs text-muted mt-1">
                  {formatLocalString(log.created_at * 1000)}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
};

export default EvolutionPanel;

export interface EvolutionPanelAuditInput {
  refreshIntervalMs: number;
  recentLogLimit: number;
  backgroundCronActive: boolean;
}

export interface EvolutionPanelAuditReport {
  refreshIntervalMs: number;
  recentLogLimit: number;
  backgroundCronActive: boolean;
  healthy: boolean;
  issueCodes: string[];
}

// eslint-disable-next-line react-refresh/only-export-components
export function evaluateEvolutionPanelGovernanceAudit(
  input: EvolutionPanelAuditInput,
): EvolutionPanelAuditReport {
  const issueCodes: string[] = [];
  if (!Number.isFinite(input.refreshIntervalMs) || input.refreshIntervalMs < 5000) {
    issueCodes.push('EVOLUTION_PANEL_REFRESH_TOO_FAST');
  }
  if (input.recentLogLimit <= 0 || input.recentLogLimit > 50) {
    issueCodes.push('EVOLUTION_PANEL_LOG_LIMIT_OUT_OF_RANGE');
  }
  if (!input.backgroundCronActive) {
    issueCodes.push('EVOLUTION_PANEL_CRON_INACTIVE');
  }
  return {
    refreshIntervalMs: input.refreshIntervalMs,
    recentLogLimit: input.recentLogLimit,
    backgroundCronActive: input.backgroundCronActive,
    healthy: issueCodes.length === 0,
    issueCodes,
  };
}
