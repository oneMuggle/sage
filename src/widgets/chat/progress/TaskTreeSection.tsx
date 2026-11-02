// src/widgets/chat/progress/TaskTreeSection.tsx
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import type { TaskBoard } from '../../../features/send-message/useChat';
import type { TaskStatusValue } from '../../../shared/api';
import { orchRunClient } from '../../../shared/api/orchRunClient';
import { usePluginNames } from '../../../shared/lib/hooks/usePluginNames';
import { findPluginToolOwner } from '../../../shared/lib/permissionInsights';

import { formatDuration, formatElapsed, formatTokens } from './progressFormat';
import { buildTaskTree, descendantsOf, flattenTree } from './taskTree';

const STATUS_ICON: Record<TaskStatusValue, string> = {
  queued: '○',
  running: '◐',
  done: '✓',
  failed: '✗',
  // P0-8 (2026-08-20): cancelled 状态渲染 —— 之前未覆盖 cancel 子任务，图标
  // 退化为 undefined，TaskTreeSection 视觉上与 running 难以区分。
  cancelled: '⊘',
  // Phase 3 (2026-10-28): 用户在步骤确认对话框选择"跳过此步"。
  skipped: '↷',
};

const STATUS_TITLE: Record<TaskStatusValue, string> = {
  queued: 'queued',
  running: 'running',
  done: 'done',
  failed: 'failed',
  cancelled: 'cancelled',
  skipped: 'skipped',
};

interface TaskTreeSectionProps {
  board: TaskBoard;
  // RV3 (round8): run 终态且有失败任务时的"重跑失败任务"入口。由上层
  // 调 rerun-failed 端点拿 planOverride 后经 chatStream 重发。
  onRerunFailed?: () => void;
  // RV4 (round27): 单任务重试入口 —— failed 行内「重试」按钮。
  onRetryTask?: (runId: string, taskId: string) => void;
  // 2026-11-02 进度面板优化: 点击任务 → 整面板切换到 TaskDetailView。
  // 不传则行不可点击（详情入口失效）。
  onSelectTask?: (taskId: string) => void;
}

export function TaskTreeSection({
  board,
  onRerunFailed,
  onRetryTask,
  onSelectTask,
}: TaskTreeSectionProps) {
  // RD21 (round42): run 触顶原因 —— 从被取消/失败任务的 error 前缀推导
  // （后端归因语义：budget_exceeded / wall_clock_exceeded，预算优先）。
  const tripReason = useMemo(() => {
    let budget = false;
    let wallClock = false;
    for (const st of Object.values(board.statuses)) {
      if (!st.error) continue;
      if (st.error.startsWith('budget_exceeded:')) budget = true;
      else if (st.error.startsWith('wall_clock_exceeded:')) wallClock = true;
    }
    if (budget) return '⚠ 预算已触顶，剩余任务已停止派发';
    if (wallClock) return '⚠ 墙钟上限已到，剩余任务已停止派发';
    return null;
  }, [board.statuses]);
  // R114: 等待审批徽章的插件归属后缀供数。子代理事件只有 tool_name、
  // 没有 plugin_name，按转录（R111）同一名单前端派生；仅当板上出现
  // 带工具名的实时数据时才取数，无编排实时数据的渲染零影响。
  const hasLiveToolNames = useMemo(
    () =>
      Object.values(board.live ?? {}).some(
        (liveState) =>
          Boolean(liveState.waitingApproval) ||
          liveState.events.some((evt) => Boolean(evt.tool_name)),
      ),
    [board.live],
  );
  const pluginNames = usePluginNames(hasLiveToolNames);
  const pluginOwnerSuffix = (toolName?: string | null): string => {
    const owner = toolName ? findPluginToolOwner(toolName, pluginNames) : null;
    return owner ? `（所属插件: ${owner}）` : '';
  };
  // B3 (2026-09-09): 单任务跳过 in-flight 集合 —— 防重复点击；终态由
  // task_status 事件驱动刷新，这里只做乐观禁用。
  const [skipping, setSkipping] = useState<ReadonlySet<string>>(new Set());

  const total = board.progress?.total ?? board.plan.length;
  const doneCount =
    board.progress?.done ??
    board.plan.filter((p) => board.statuses[p.task_id]?.status === 'done').length;
  // 进度可视化 P0-2 (2026-08-12): 5 元组快照,优先从 progress 取 done/
  // running/queued/failed,后续 ProgressSection 与 TaskTreeSection 文案
  // 共享同一数据源(避免"总分不一致"的视觉冲突)。fallback 到实时聚合
  // 兼容老 run(只有 task_status 流入没 task_progress 的情况)。
  const progress = board.progress;
  const running = progress?.running ?? 0;
  const queued = progress?.queued ?? 0;
  const failed = progress?.failed ?? 0;
  const cancelled = progress?.cancelled ?? 0;
  const inFlight = running + queued;
  // 进度可视化 L2 修正 (2026-08-12): 全部完成时不再显示"等待结果中"，
  // 避免与下方 "完成 6/6" 自相矛盾。
  const allDone = doneCount + failed + cancelled === total && inFlight === 0;
  // BU15 (round29): 存在 running 任务时 1s tick 驱动实时计时徽章；
  // 全部终态后停止定时器（避免终态面板无谓重渲染）。
  const inFlightTasks = useMemo(
    () =>
      Object.values(board.statuses).filter(
        (st) => st.status === 'running' || st.status === 'queued',
      ).length,
    [board.statuses],
  );
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (inFlightTasks === 0) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [inFlightTasks]);

  // 任务层级（spec 2026-09-19）：把平铺计划索引成树，支持缩进与折叠。
  // 旧计划（无 parent_task_id）全部为根 → 渲染结果与既有平铺一致。
  const treeIndex = useMemo(() => buildTaskTree(board.plan), [board.plan]);
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());
  const visibleRows = useMemo(() => {
    const hidden = new Set<string>();
    for (const taskId of collapsed) {
      for (const descendant of descendantsOf(treeIndex, taskId)) {
        hidden.add(descendant);
      }
    }
    // flattenTree 自带 visited 守卫（父链成环时不会无限递归）。
    return flattenTree(treeIndex).filter((node) => !hidden.has(node.item.task_id));
  }, [treeIndex, collapsed]);

  const toggleCollapsed = (taskId: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(taskId)) next.delete(taskId);
      else next.add(taskId);
      return next;
    });
  };

  // B3 (2026-09-09): 单任务跳过 —— 只停该子任务；后端 task_status 事件把
  // 状态收敛到 cancelled，依赖它的下游由级联闭包置 failed。
  const handleTaskSkip = (taskId: string) => {
    if (skipping.has(taskId)) return;
    setSkipping((prev) => new Set(prev).add(taskId));
    orchRunClient
      .cancelTask(board.runId, taskId)
      .then(() => toast.info(`已请求跳过子任务 ${taskId}`))
      .catch(() => {
        toast.error(`跳过子任务 ${taskId} 失败（已结束?）`);
        setSkipping((prev) => {
          const next = new Set(prev);
          next.delete(taskId);
          return next;
        });
      });
  };

  return (
    <div className="space-y-1" data-testid="task-tree">
      {/* RD21 (round42): run 触顶原因横幅 —— 用户侧直读"为什么停"。 */}
      {tripReason && (
        <div
          data-testid="task-tree-trip-reason"
          className="text-xs text-error px-2 py-1 rounded bg-error/10"
        >
          {tripReason}
        </div>
      )}
      {/* RV3 (round8): 终态且有失败任务 → 重跑失败任务（已完成结果保留）。
          run 级汇总（完成数 / 耗时 / token）已上移到 StatusBar 常驻顶栏。 */}
      {allDone && failed > 0 && onRerunFailed && (
        <button
          type="button"
          onClick={onRerunFailed}
          data-testid="task-tree-rerun-failed"
          title="只重跑失败/取消的子任务，已完成子任务的结果保留"
          className="px-2 py-1 text-xs border border-primary/40 text-primary rounded shrink-0 hover:bg-primary/10 transition-colors"
        >
          重跑失败任务
        </button>
      )}
      {/* P0-6 (2026-08-20): reviewer 复核结论横幅 —— pass/fail 双色 */}
      {board.review && (
        <div
          data-testid="task-review-banner"
          className={`px-2 py-1 rounded text-xs ${
            board.review.verdict === 'pass'
              ? 'bg-primary/10 text-primary'
              : 'bg-error/10 text-error'
          }`}
        >
          {board.review.verdict === 'pass'
            ? `✓ 复核通过（${board.review.assertion_count} 项断言）`
            : `⚠ 复核存疑（${board.review.assertion_count} 项断言）：${board.review.summary}`}
        </div>
      )}
      {visibleRows.map(({ item, depth, childIds }) => {
        const st = board.statuses[item.task_id];
        const status: TaskStatusValue = st?.status ?? 'queued';
        // live-events P0 (2026-09-06): 子代理实时执行态（subagent_event 镜像）。
        const live = board.live?.[item.task_id];
        // P1-6 (2026-08-14): depends_on 透传 —— 有依赖的任务缩进 + 标记行。
        const dependsOn = item.depends_on ?? [];
        const hasDeps = dependsOn.length > 0;
        const hasChildren = childIds.length > 0;
        const isCollapsed = collapsed.has(item.task_id);
        const clickable = Boolean(onSelectTask);
        return (
          <div
            key={item.task_id}
            data-testid={`task-tree-item-${item.task_id}`}
            data-depth={depth}
            style={depth > 0 ? { paddingLeft: depth * 16 } : undefined}
            className={`flex flex-col gap-1 px-2 py-1 rounded text-xs bg-bg-hover ${
              clickable ? 'cursor-pointer hover:bg-bg-active transition-colors' : ''
            } ${hasDeps ? 'ml-4' : ''}`}
            onClick={() => onSelectTask?.(item.task_id)}
            role={clickable ? 'button' : undefined}
            tabIndex={clickable ? 0 : undefined}
            onKeyDown={(event) => {
              if (!clickable) return;
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                onSelectTask?.(item.task_id);
              }
            }}
          >
            <div className="flex items-center gap-2">
              {/* 任务层级（spec 2026-09-19）：有子任务时提供折叠/展开入口。
                  stopPropagation 防止触发整行点击。 */}
              {hasChildren && (
                <button
                  type="button"
                  data-testid={`task-tree-toggle-${item.task_id}`}
                  aria-label={isCollapsed ? `展开 ${item.goal}` : `折叠 ${item.goal}`}
                  aria-expanded={!isCollapsed}
                  className="w-3 text-ui-2xs text-text-tertiary hover:text-text-secondary shrink-0"
                  onClick={(event) => {
                    event.stopPropagation();
                    toggleCollapsed(item.task_id);
                  }}
                >
                  {isCollapsed ? '▶' : '▼'}
                </button>
              )}
              <span title={STATUS_TITLE[status]} className="w-4 text-center">
                {STATUS_ICON[status]}
              </span>
              {/* BU15 (round29): 运行中实时耗时 —— 卡住的子任务一眼可辨。 */}
              {status === 'running' && st?.runningSince && (
                <span
                  data-testid={`task-tree-elapsed-${item.task_id}`}
                  className="text-text-tertiary text-ui-2xs shrink-0 tabular-nums"
                >
                  {formatElapsed(now - st.runningSince)}
                </span>
              )}
              <span className="px-1 rounded bg-primary/10 text-primary">{item.agent_id}</span>
              <span className="text-text-secondary flex-1">{item.goal}</span>
              {/* B3 (2026-09-09): 单任务跳过 —— queued/running 行内按钮；
                  stopPropagation 防触发整行点击。 */}
              {board.runId && (status === 'queued' || status === 'running') && (
                <button
                  type="button"
                  data-testid={`task-tree-skip-${item.task_id}`}
                  disabled={skipping.has(item.task_id)}
                  title="跳过该子任务（依赖它的下游将级联失败）"
                  className="px-1.5 py-0.5 text-ui-2xs border border-border rounded text-text-secondary hover:text-error hover:border-error/40 shrink-0 disabled:opacity-50"
                  onClick={(event) => {
                    event.stopPropagation();
                    handleTaskSkip(item.task_id);
                  }}
                >
                  {skipping.has(item.task_id) ? '跳过中…' : '跳过'}
                </button>
              )}
              {/* RV4 (round27): 单任务重试 —— failed 行内按钮；run 终态才可重试
                 （rerun-failed 端点对 running run 返 409）。stopPropagation
                  防触发整行点击。 */}
              {onRetryTask && board.runId && allDone && status === 'failed' && (
                <button
                  type="button"
                  data-testid={`task-tree-retry-${item.task_id}`}
                  title="只重试该任务（其下游未完成任务将一并重建，已完成任务结果保留）"
                  className="px-1.5 py-0.5 text-ui-2xs border border-border rounded text-text-secondary hover:text-primary hover:border-primary/40 shrink-0"
                  onClick={(event) => {
                    event.stopPropagation();
                    onRetryTask(board.runId!, item.task_id);
                  }}
                >
                  重试
                </button>
              )}
              {/* P0-7 (2026-08-20): 重试徽章 —— retry_count>0 才显示 */}
              {(st?.retry_count ?? 0) > 0 && (
                <span
                  data-testid={`task-tree-retry-${item.task_id}`}
                  className="text-text-tertiary text-ui-2xs shrink-0"
                >
                  已重试 ×{st?.retry_count}
                </span>
              )}
              {/* BU13 (round24): 终态任务消耗/耗时徽章 —— per-task 归因值，
                  任一存在即展示（对标 Claude Code per-task token + 耗时）。 */}
              {(st?.used_tokens ?? 0) > 0 || (st?.duration_ms ?? 0) > 0 ? (
                <span
                  data-testid={`task-tree-usage-${item.task_id}`}
                  className="text-text-tertiary text-ui-2xs shrink-0"
                >
                  {(st?.used_tokens ?? 0) > 0 && formatTokens(st!.used_tokens!)}
                  {(st?.used_tokens ?? 0) > 0 && (st?.duration_ms ?? 0) > 0 && ' · '}
                  {(st?.duration_ms ?? 0) > 0 && formatDuration(st!.duration_ms!)}
                </span>
              ) : null}
              {/* RD18 (round33): 级联跳过根因徽章 —— 上游失败导致本任务
                  未启动即置 failed（error 前缀 blocked_by_failed:<root>），
                  行内直读根因，不必开详情翻原始文本。 */}
              {status === 'failed' && st?.error?.startsWith('blocked_by_failed:') && (
                <span
                  data-testid={`task-tree-blocked-${item.task_id}`}
                  title={st.error}
                  className="text-text-tertiary text-ui-2xs shrink-0"
                >
                  因 {st.error.slice('blocked_by_failed:'.length).split(',').join('、')}{' '}
                  失败级联跳过
                </span>
              )}
              {/* RD13+ (round15): 重派徽章 —— retry_of 重派的任务可追溯 */}
              {st?.retry_of && (
                <span
                  data-testid={`task-tree-redeploy-${item.task_id}`}
                  title={`重派自失败任务 ${st.retry_of}`}
                  className="text-primary text-ui-2xs shrink-0"
                >
                  重派
                </span>
              )}
              {/* RP1 (round34, 2026-09-19): 已调整徽章 —— conductor 在 run 中
                  改过目标 / 新增 / 取消过该任务时携带，用户可追溯哪些任务偏离
                  了初始计划（与"重派"徽章区分：重派是同任务重做，已调整是计划
                  本身被改）。 */}
              {st?.adjusted && (
                <span
                  data-testid={`task-tree-adjusted-${item.task_id}`}
                  title="该任务的计划由 AI 在执行过程中调整"
                  className="text-warning text-ui-2xs shrink-0"
                >
                  已调整
                </span>
              )}
            </div>
            {/* live-events P0: 等待审批徽章（ApprovalDialog 之外的行内提示） */}
            {live?.waitingApproval && status === 'running' && (
              <div
                data-testid={`task-tree-approval-${item.task_id}`}
                className="pl-6 text-ui-2xs text-warning"
              >
                ⏳ 等待审批: {live.waitingApproval}
                {pluginOwnerSuffix(live.waitingApproval)}
              </div>
            )}
            {/* live-events P0: 行内实时步骤（running 时显示最新一条投影） */}
            {live?.liveStep && status === 'running' && (
              <div
                data-testid={`task-tree-live-${item.task_id}`}
                className="pl-6 text-ui-2xs text-primary animate-pulse truncate"
              >
                {live.liveStep}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
