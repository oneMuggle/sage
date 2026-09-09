// src/widgets/chat/progress/TaskTreeSection.tsx
import { useState } from 'react';
import { toast } from 'sonner';

import { useRunControlStore } from '../../../entities/orchestration/runControlStore';
// TaskStatusValue 定义在 shared/api（Task 7 已 re-export），不从 useChat import
import type { TaskBoard } from '../../../features/send-message/useChat';
import type { TaskStatusValue } from '../../../shared/api';
import { orchRunClient } from '../../../shared/api/orchRunClient';
import { orchRunControlClient } from '../../../shared/api/orchRunControlClient';

import { SubagentDetailDrawer } from './SubagentDetailDrawer';

const STATUS_ICON: Record<TaskStatusValue, string> = {
  queued: '○',
  running: '◐',
  done: '✓',
  failed: '✗',
  // P0-8 (2026-08-20): cancelled 状态渲染 —— 之前未覆盖 cancel 子任务，图标
  // 退化为 undefined，TaskTreeSection 视觉上与 running 难以区分。
  cancelled: '⊘',
};

const STATUS_TITLE: Record<TaskStatusValue, string> = {
  queued: 'queued',
  running: 'running',
  done: 'done',
  failed: 'failed',
  cancelled: 'cancelled',
};

interface TaskTreeSectionProps {
  board: TaskBoard;
  // Wave 3 H2 (2026-08-15): 运行中编排的取消入口。由上层
  // (Chat.handleCancelRun) 统一调 cancelRun + 清空 taskBoard。
  onCancel?: () => void;
}

export function TaskTreeSection({ board, onCancel }: TaskTreeSectionProps) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const selectTask = useRunControlStore((s) => s.selectTask);
  // B3 (2026-09-09): 单任务跳过 in-flight 集合 —— 防重复点击；终态由
  // task_status 事件驱动刷新，这里只做乐观禁用。
  const [skipping, setSkipping] = useState<ReadonlySet<string>>(new Set());
  // live-events P1: run 级审批模式开关（乐观更新，后端 approval_mode 事件
  // 回显为准；失败回滚到 board 上的值）。
  const [approvalMode, setApprovalMode] = useState<'ask' | 'auto'>(
    board.approvalMode ?? 'ask',
  );
  const [approvalPending, setApprovalPending] = useState(false);

  const toggleApprovalMode = () => {
    if (approvalPending) return;
    const next = approvalMode === 'auto' ? 'ask' : 'auto';
    setApprovalPending(true);
    setApprovalMode(next); // 乐观
    orchRunControlClient
      .setApprovalMode({ run_id: board.runId, mode: next })
      .catch(() => {
        setApprovalMode(board.approvalMode ?? 'ask'); // 回滚
        toast.error('审批模式切换失败（run 已结束?）');
      })
      .finally(() => setApprovalPending(false));
  };

  const handleTaskClick = (taskId: string, runId: string) => {
    selectTask(runId, taskId);
    setDrawerOpen(true);
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

  const handleCloseDrawer = () => {
    setDrawerOpen(false);
  };

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

  return (
    <div className="space-y-1" data-testid="task-tree">
      {!allDone && (
        <div className="text-xs text-text-secondary">已拆解为 {total} 个子任务,等待结果中…</div>
      )}
      <div className="flex items-center justify-between gap-2">
        <div className="text-xs text-text-secondary">
          完成 {doneCount}/{total}
          {inFlight > 0 && ` · ${inFlight} 个进行中`}
          {failed > 0 && <span className="text-error ml-1">({failed} 失败)</span>}
          {cancelled > 0 && <span className="text-text-secondary ml-1">({cancelled} 已取消)</span>}
        </div>
        {/* live-events P1 (2026-09-06): run 级子代理审批模式开关 —— auto =
            非危险工具自动批准（破坏性/可疑/边界升级仍弹审批）。仅活动 run
            显示；后端 approval_mode 事件到达后 board.approvalMode 对齐。 */}
        {!allDone && board.runId && (
          <button
            type="button"
            onClick={toggleApprovalMode}
            disabled={approvalPending}
            data-testid="task-tree-approval-mode"
            title="自动批准子代理的非危险工具调用（破坏性/可疑命令仍需确认）"
            className={`px-2 py-1 text-xs border rounded shrink-0 transition-colors disabled:opacity-50 ${
              approvalMode === 'auto'
                ? 'border-primary/40 bg-primary/10 text-primary'
                : 'border-border text-text-secondary'
            }`}
          >
            {approvalMode === 'auto' ? '⚡ 自动批准：开' : '⚡ 自动批准：关'}
          </button>
        )}
        {/* Wave 3 H2 (2026-08-15): 运行中取消按钮 —— 全部完成/无 onCancel 时隐藏 */}
        {!allDone && onCancel && (
          <button
            type="button"
            onClick={onCancel}
            data-testid="task-tree-cancel"
            className="px-2 py-1 text-xs border rounded shrink-0"
          >
            取消执行
          </button>
        )}
      </div>
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
      {board.plan.map((item) => {
        const st = board.statuses[item.task_id];
        const status: TaskStatusValue = st?.status ?? 'queued';
        const preview = st?.output_preview ?? st?.error ?? null;
        // live-events P0 (2026-09-06): 子代理实时执行态（subagent_event 镜像）。
        const live = board.live?.[item.task_id];
        const recentEvents = live ? [...live.events].reverse().slice(0, 10) : [];
        // P1-6 (2026-08-14): depends_on 透传 —— 有依赖的任务缩进 + 标记行。
        const dependsOn = item.depends_on ?? [];
        const hasDeps = dependsOn.length > 0;
        return (
          <div
            key={item.task_id}
            data-testid={`task-tree-item-${item.task_id}`}
            className={`flex flex-col gap-1 px-2 py-1 rounded text-xs bg-bg-hover cursor-pointer hover:bg-bg-active transition-colors ${
              hasDeps ? 'ml-4' : ''
            }`}
            onClick={() => handleTaskClick(item.task_id, board.runId)}
            role="button"
            tabIndex={0}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                handleTaskClick(item.task_id, board.runId);
              }
            }}
          >
            {hasDeps && (
              <div
                className="text-text-tertiary text-[10px]"
                data-testid={`task-tree-deps-${item.task_id}`}
              >
                ↳ 依赖 {dependsOn.join(', ')}
              </div>
            )}
            <div className="flex items-center gap-2">
              <span title={STATUS_TITLE[status]} className="w-4 text-center">
                {STATUS_ICON[status]}
              </span>
              <span className="px-1 rounded bg-primary/10 text-primary">{item.agent_id}</span>
              <span className="text-text-secondary flex-1">{item.goal}</span>
              {/* B3 (2026-09-09): 单任务跳过 —— queued/running 行内按钮；
                  stopPropagation 防触发整行的 Drawer 点击。 */}
              {board.runId && (status === 'queued' || status === 'running') && (
                <button
                  type="button"
                  data-testid={`task-tree-skip-${item.task_id}`}
                  disabled={skipping.has(item.task_id)}
                  title="跳过该子任务（依赖它的下游将级联失败）"
                  className="px-1.5 py-0.5 text-[10px] border border-border rounded text-text-secondary hover:text-error hover:border-error/40 shrink-0 disabled:opacity-50"
                  onClick={(event) => {
                    event.stopPropagation();
                    handleTaskSkip(item.task_id);
                  }}
                >
                  {skipping.has(item.task_id) ? '跳过中…' : '跳过'}
                </button>
              )}
              {/* P0-7 (2026-08-20): 重试徽章 —— retry_count>0 才显示 */}
              {(st?.retry_count ?? 0) > 0 && (
                <span
                  data-testid={`task-tree-retry-${item.task_id}`}
                  className="text-text-tertiary text-[10px] shrink-0"
                >
                  已重试 ×{st?.retry_count}
                </span>
              )}
            </div>
            {/* live-events P0: 等待审批徽章（ApprovalDialog 之外的行内提示） */}
            {live?.waitingApproval && status === 'running' && (
              <div
                data-testid={`task-tree-approval-${item.task_id}`}
                className="pl-6 text-[11px] text-warning"
              >
                ⏳ 等待审批: {live.waitingApproval}
              </div>
            )}
            {/* live-events P0: 行内实时步骤（running 时显示最新一条投影） */}
            {live?.liveStep && status === 'running' && (
              <div
                data-testid={`task-tree-live-${item.task_id}`}
                className="pl-6 text-[11px] text-primary animate-pulse truncate"
              >
                {live.liveStep}
              </div>
            )}
            {/* live-events P0: 最近事件环形缓冲（最多展示最近 10 条,尾新头旧） */}
            {recentEvents.length > 0 && (
              <details className="pl-6">
                <summary className="text-[11px] text-muted">
                  实时动态（{live!.events.length} 条）
                </summary>
                <ul
                  data-testid={`task-tree-events-${item.task_id}`}
                  className="mt-1 space-y-0.5 text-muted"
                >
                  {recentEvents.map((evt, idx) => (
                    <li key={`${evt.ts ?? idx}-${idx}`} className="truncate">
                      <span className="text-text-tertiary">
                        {evt.ts ? new Date(evt.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : ''}
                      </span>{' '}
                      {evt.phase === 'approval_requested'
                        ? `⏳ 等待审批: ${evt.tool_name ?? 'tool'}`
                        : evt.phase === 'approval_resolved'
                          ? evt.approved
                            ? '✓ 已批准'
                            : '✗ 已拒绝'
                          : evt.phase === 'question'
                            ? '❓ 向用户提问'
                            : evt.phase === 'failed'
                              ? '✗ 失败'
                              : evt.phase === 'tool_result'
                                ? `👀 ${evt.tool_name ?? 'tool'} ${evt.is_error ? '（错误）' : ''}`
                                : `🔧 ${evt.tool_name ?? 'tool'}`}
                    </li>
                  ))}
                </ul>
              </details>
            )}
            {preview && status !== 'queued' && (
              <details className="pl-6 text-muted">
                <summary>{status === 'failed' ? '错误详情' : '结果预览'}</summary>
                <pre className="mt-1 whitespace-pre-wrap">{preview}</pre>
              </details>
            )}
          </div>
        );
      })}
      <SubagentDetailDrawer open={drawerOpen} onClose={handleCloseDrawer} />
    </div>
  );
}
