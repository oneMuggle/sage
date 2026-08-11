// src/widgets/chat/progress/ProgressSection.tsx
import type { ToolCall } from '../../../shared/lib/store';
// Multi-Agent Orchestration: 编排任务板聚合状态
import type { TaskBoard } from '../../../features/send-message/useChat';
import { TaskTreeSection } from './TaskTreeSection';

interface ProgressSectionProps {
  iteration: number;
  streamingState: string | null;
  toolCalls: ToolCall[];
  isLoading: boolean;
  taskBoard?: TaskBoard | null;   // 新增：编排任务板（null/缺省 = 无编排）
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
  toolCalls,
  isLoading,
  taskBoard,
}: ProgressSectionProps) {
  const stateLabel = streamingState ? STATE_LABELS[streamingState] ?? streamingState : null;

  return (
    <div className="p-3 space-y-2 text-sm">
      <div className="flex items-center gap-2">
        {isLoading && stateLabel && <span className="text-primary font-medium">{stateLabel}</span>}
        {iteration > 0 && <span className="text-text-secondary">第 {iteration} 轮</span>}
        {!isLoading && !stateLabel && <span className="text-muted">等待输入...</span>}
      </div>

      {/* Multi-Agent Orchestration: 编排任务板非空 → 任务树；空 plan/无编排 → 回落既有 tool-call 列表 */}
      {taskBoard ? (
        <TaskTreeSection board={taskBoard} />
      ) : (
        toolCalls.length > 0 && (
          <div className="space-y-1">
            {toolCalls.map((tc, i) => (
              <div
                key={tc.id ?? `${tc.name}-${i}`}
                className="flex items-center gap-2 px-2 py-1 rounded text-xs bg-bg-hover"
              >
                <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
                <span className="text-text-secondary">{tc.name}</span>
              </div>
            ))}
          </div>
        )
      )}
    </div>
  );
}
