// src/widgets/chat/progress/ProgressSection.tsx
import type { ToolCall } from '../../../shared/lib/store';

interface ProgressSectionProps {
  iteration: number;
  streamingState: string | null;
  toolCalls: ToolCall[];
  isLoading: boolean;
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
}: ProgressSectionProps) {
  const stateLabel = streamingState ? STATE_LABELS[streamingState] ?? streamingState : null;

  return (
    <div className="p-3 space-y-2 text-sm">
      <div className="flex items-center gap-2">
        {isLoading && stateLabel && <span className="text-primary font-medium">{stateLabel}</span>}
        {iteration > 0 && <span className="text-text-secondary">第 {iteration} 轮</span>}
        {!isLoading && !stateLabel && <span className="text-muted">等待输入...</span>}
      </div>

      {toolCalls.length > 0 && (
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
      )}
    </div>
  );
}
