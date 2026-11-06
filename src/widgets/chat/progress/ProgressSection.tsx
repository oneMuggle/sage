// src/widgets/chat/progress/ProgressSection.tsx
// Fix #2 (2026-09-06): PlanCard 已移至 Chat.tsx 主对话区域,此处仅保留状态摘要 + 任务树。
// UI 优化 2026-10-14: 顶部增加 sub-tab 切换「实时进度 / 完整轨迹」。
// 轨迹原为独立 RightPanel Tab，合并入此组件作为第二个 sub-tab 视图。
// 2026-11-02 进度面板优化: sub-tab 三切分「概览 / 任务 / 轨迹」。
// 此前一个视图里同时塞了任务清单 + 编排计划 + 子代理执行情况，信息密度过高、
// 需要滚动才能找到重点。切分后：
//   概览 = StatusBar(常驻顶栏) + 焦点卡 + 任务清单 + 历史运行
//   任务 = 任务树（点击行 → 整面板切到 TaskDetailView 看实时运行情况）
//   轨迹 = 完整轨迹（原样保留）
import { useState } from 'react';

import {
  useChatStreamStore,
  selectSessionSlots,
} from '../../../features/send-message/chatStreamStore';
import type { TaskBoard } from '../../../features/send-message/useChat';
import type { ToolCall } from '../../../shared/lib/store';
import { TrajectoryPane } from '../TrajectoryPane';

// Multi-Agent Orchestration: 编排任务板聚合状态
import { BackgroundShellsSection } from './BackgroundShellsSection';
import { CurrentTaskFocus } from './CurrentTaskFocus';
import { SessionRunHistory } from './SessionRunHistory';
import { StatusBar } from './StatusBar';
import { TaskDetailView } from './TaskDetailView';
import { TaskTreeSection } from './TaskTreeSection';
// P1 todo 接线 (2026-08-21): agent 自维护任务清单
import { TodoListSection } from './TodoListSection';

type ProgressSubTab = 'overview' | 'tasks' | 'trajectory';

interface ProgressSectionProps {
  iteration: number;
  streamingState: string | null;
  toolCalls: ToolCall[];
  isLoading: boolean;
  taskBoard?: TaskBoard | null; // 新增：编排任务板（null/缺省 = 无编排）
  // S2 (2026-09-06): todos 改从该会话的键控槽位读取（并行会话各自的清单）
  sessionId?: string | null;
  // Wave 3 (2026-08-14): 计划卡接线回调。
  // M4 (2026-08-15): onPlanStart 已删 —— PlanCard.handleStart 内部
  // 自调 updatePlan 落库，派发由后端驱动，前端无需计划开始回调。
  // Wave 4 (2026-09-06): onResumeRun 已删 —— 历史编排记录功能移除。
  onCancelExecution?: (runId: string) => void;
  // RV3 (round8): 终态且有失败任务时的"重跑失败任务"入口。
  onRerunFailed?: (runId: string) => void;
  // RV4 (round27): 单任务重试入口透传。
  onRetryTask?: (runId: string, taskId: string) => void;
  // RD23 (round52): 历史编排选取回调透传。
  onSelectRun?: (run: import('../../../shared/api/orchRunClient').OrchRunDetail) => void;
}

const STATE_LABELS: Record<string, string> = {
  thinking: '思考中',
  tool_call: '调用工具',
  generating: '生成回复',
  idle: '空闲',
};

export interface ProgressSectionExportParams {
  iteration: number;
  streamingState: string | null;
  isLoading: boolean;
  taskBoard?: TaskBoard | null;
  todosCount?: number;
}

export function formatProgressSectionMarkdown(params: ProgressSectionExportParams): string {
  const stateLabel = params.streamingState
    ? (STATE_LABELS[params.streamingState] ?? params.streamingState)
    : '空闲';
  const lines = [
    '# 进度面板摘要',
    `- 状态: ${stateLabel}`,
    `- 加载中: ${params.isLoading ? '是' : '否'}`,
    `- 轮次: ${params.iteration}`,
    `- 待办数: ${params.todosCount ?? 0}`,
  ];
  if (params.taskBoard) {
    lines.push(
      `- 编排运行: ${params.taskBoard.runId} (${params.taskBoard.dispatchedAt ? '已派发' : '计划待执行'})`,
    );
    const p = params.taskBoard.progress;
    if (p) {
      const inFlight = (p.queued ?? 0) + (p.running ?? 0);
      lines.push(
        `- 编排进度: ${p.done}/${p.total} 完成 · 进行中 ${inFlight} · 失败 ${p.failed} · 取消 ${p.cancelled}`,
      );
    }
  }
  return lines.join('\n');
}

export function formatProgressSectionJson(params: ProgressSectionExportParams): string {
  return JSON.stringify(
    {
      iteration: params.iteration,
      streamingState: params.streamingState,
      isLoading: params.isLoading,
      todosCount: params.todosCount ?? 0,
      taskBoard: params.taskBoard
        ? {
            runId: params.taskBoard.runId,
            dispatched: params.taskBoard.dispatchedAt != null,
            planCount: params.taskBoard.plan.length,
            progress: params.taskBoard.progress ?? null,
          }
        : null,
    },
    null,
    2,
  );
}

export function ProgressSection({
  iteration,
  streamingState,
  isLoading,
  taskBoard,
  sessionId,
  onCancelExecution,
  onRerunFailed,
  onRetryTask,
  onSelectRun,
}: ProgressSectionProps) {
  // 2026-11-02 进度面板优化: sub-tab 三切分 + 常驻状态栏 + 整面板任务详情。
  const [subTab, setSubTab] = useState<ProgressSubTab>('overview');
  // 打开任务详情（整面板替换）；null = 回到任务列表。
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  // P1 todo 接线: agent 自维护清单快照（组件内直取 store，减少 prop drilling）。
  // S2: 按会话键控 —— 显示的是当前打开会话的清单。
  const todos = useChatStreamStore((s) => selectSessionSlots(s, sessionId).todos);

  const openTaskDetail = (taskId: string) => setSelectedTaskId(taskId);
  const closeTaskDetail = () => setSelectedTaskId(null);

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* 常驻顶栏 —— 状态 / 进度条 / run 级汇总与操作，任何视图下都可见。 */}
      <StatusBar
        streamingState={streamingState}
        isLoading={isLoading}
        iteration={iteration}
        board={taskBoard ?? null}
        onCancel={taskBoard ? () => onCancelExecution?.(taskBoard.runId) : undefined}
      />

      {selectedTaskId && taskBoard ? (
        /* 任务详情 —— 整面板替换。旧的 SubagentDetailDrawer 嵌在右栏里宽度被裁切，
           且从编排 store 解析聊天任务恒为 undefined（点了没反应）；此处占满面板。 */
        <div className="flex-1 min-h-0">
          <TaskDetailView
            board={taskBoard}
            taskId={selectedTaskId}
            onBack={closeTaskDetail}
            onRetryTask={onRetryTask}
          />
        </div>
      ) : (
        <>
          {/* sub-tab 切换行 —— 概览 / 任务 / 轨迹 */}
          <div className="flex border-b border-border shrink-0">
            <button
              type="button"
              className={`flex-1 py-2 text-xs font-medium transition-colors ${
                subTab === 'overview'
                  ? 'text-primary border-b-2 border-primary'
                  : 'text-text-secondary hover:text-text'
              }`}
              onClick={() => setSubTab('overview')}
              data-testid="progress-subtab-overview"
            >
              概览
            </button>
            <button
              type="button"
              className={`flex-1 py-2 text-xs font-medium transition-colors ${
                subTab === 'tasks'
                  ? 'text-primary border-b-2 border-primary'
                  : 'text-text-secondary hover:text-text'
              }`}
              onClick={() => setSubTab('tasks')}
              data-testid="progress-subtab-tasks"
            >
              任务
            </button>
            <button
              type="button"
              className={`flex-1 py-2 text-xs font-medium transition-colors ${
                subTab === 'trajectory'
                  ? 'text-primary border-b-2 border-primary'
                  : 'text-text-secondary hover:text-text'
              }`}
              onClick={() => setSubTab('trajectory')}
              data-testid="progress-subtab-trajectory"
            >
              完整轨迹
            </button>
          </div>

          {subTab === 'trajectory' ? (
            <div className="flex-1 min-h-0 overflow-y-auto">
              <TrajectoryPane sessionId={sessionId ?? null} />
            </div>
          ) : (
            <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-3">
              {subTab === 'overview' && (
                <>
                  {/* 焦点卡 —— 回答"现在到底在做什么"，把正在跑的那一个子任务提到最上面。 */}
                  <CurrentTaskFocus board={taskBoard ?? null} onOpenTask={openTaskDetail} />
                  {/* 任务清单 —— agent 自维护；编排计划已由「任务」子视图统一承载。 */}
                  <TodoListSection todos={todos} />
                  {/* 2026-11-06 Phase 3: 后台 shell 列表 + 实时输出 */}
                  <BackgroundShellsSection />
                  {sessionId && onSelectRun && (
                    <SessionRunHistory
                      sessionId={sessionId}
                      onSelectRun={onSelectRun}
                      excludeRunId={taskBoard?.runId}
                    />
                  )}
                </>
              )}
              {subTab === 'tasks' &&
                (taskBoard?.dispatchedAt ? (
                  <TaskTreeSection
                    board={taskBoard}
                    onRerunFailed={() => onRerunFailed?.(taskBoard.runId)}
                    onRetryTask={onRetryTask}
                    onSelectTask={openTaskDetail}
                  />
                ) : (
                  <div className="text-xs text-text-tertiary" data-testid="task-tree-empty">
                    暂无已派发的编排任务
                  </div>
                ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
