// src/widgets/chat/progress/ProgressSection.tsx
import { PlanCard } from '../../../components/PlanCard';
import { PlanCardList } from '../../../components/PlanCardList';
import type { TaskBoard } from '../../../features/send-message/useChat';
import type { TaskPlanItem } from '../../../shared/api/types';
import type { ToolCall } from '../../../shared/lib/store';

// Multi-Agent Orchestration: 编排任务板聚合状态
import { TaskTreeSection } from './TaskTreeSection';

interface ProgressSectionProps {
  iteration: number;
  streamingState: string | null;
  toolCalls: ToolCall[];
  isLoading: boolean;
  taskBoard?: TaskBoard | null; // 新增：编排任务板（null/缺省 = 无编排）
  // Wave 3 (2026-08-14): 历史恢复 / 计划卡接线回调。
  onResumeRun?: (runId: string) => void;
  onCancelExecution?: (runId: string) => void;
  onPlanStart?: (runId: string, plan: TaskPlanItem[]) => void;
}

const STATE_LABELS: Record<string, string> = {
  thinking: '思考中',
  tool_call: '调用工具',
  generating: '生成回复',
  idle: '空闲',
};

export function ProgressSection({
  iteration,
  streamingState,
  isLoading,
  taskBoard,
  onResumeRun,
  onCancelExecution,
  onPlanStart,
}: ProgressSectionProps) {
  const stateLabel = streamingState ? (STATE_LABELS[streamingState] ?? streamingState) : null;
  // 进度可视化 P0-2 (2026-08-12): 编排进行中有 taskBoard 时,用 5 元组
  // 摘要替代"等待输入"占位文,避免误导用户以为主进程空闲。
  // C3 (2026-08-15): 三态 —— 仅已派发(dispatchedAt)显示 5 元组;
  // 未派发显示「计划待执行」;无 taskBoard 回落原状态机文案。
  const progress = taskBoard?.progress;
  const hasTaskBoard = taskBoard != null;
  const isDispatched = hasTaskBoard && taskBoard.dispatchedAt != null;
  const showProgress = isDispatched && progress != null;
  // 进度可视化 M2 修正 (2026-08-12): "进行中"口径与 TaskTreeSection 一致
  // （queued + running 都算未完成），避免同一面板两行文案数字矛盾。
  const inFlight = (progress?.queued ?? 0) + (progress?.running ?? 0);

  return (
    <div className="p-3 space-y-2 text-sm">
      <div className="flex items-center gap-2">
        {isLoading && stateLabel && <span className="text-primary font-medium">{stateLabel}</span>}
        {iteration > 0 && <span className="text-text-secondary">第 {iteration} 轮</span>}
        {showProgress && progress && (
          <span className="text-primary" data-testid="task-progress-summary">
            编排任务 {progress.done}/{progress.total} 完成
            {inFlight > 0 && <span className="text-text-secondary"> · {inFlight} 个进行中</span>}
            {progress.failed > 0 && (
              <span className="text-error ml-1">({progress.failed} 失败)</span>
            )}
          </span>
        )}
        {hasTaskBoard && !isDispatched && (
          <span className="text-primary" data-testid="plan-pending-label">
            计划待执行
          </span>
        )}
        {!hasTaskBoard && !showProgress && !isLoading && !stateLabel && (
          <span className="text-muted">等待输入...</span>
        )}
      </div>

      {/* Wave 3 C3 (2026-08-15): 三态 —— 无编排→历史记录;未派发→计划卡(可编辑);已派发→任务树 */}
      {taskBoard == null ? (
        <PlanCardList onResume={onResumeRun ?? (() => {})} />
      ) : taskBoard.dispatchedAt ? (
        <TaskTreeSection board={taskBoard} />
      ) : (
        <PlanCard
          runId={taskBoard.runId}
          plan={taskBoard.plan}
          locked={false}
          onCancel={() => onCancelExecution?.(taskBoard.runId)}
          // C4: 已派发(locked)取消 → PlanCard 内部 cancelRun + onCancelled,
          // 统一回落 onCancelExecution(上层 clearTaskBoard)。
          onCancelled={() => onCancelExecution?.(taskBoard.runId)}
          onStart={(updated) => onPlanStart?.(taskBoard.runId, updated)}
        />
      )}
    </div>
  );
}
