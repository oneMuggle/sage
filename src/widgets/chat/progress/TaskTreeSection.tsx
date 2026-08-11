// src/widgets/chat/progress/TaskTreeSection.tsx
import type { TaskBoard } from '../../../features/send-message/useChat';
// TaskStatusValue 定义在 shared/api（Task 7 已 re-export），不从 useChat import
import type { TaskStatusValue } from '../../../shared/api';

const STATUS_ICON: Record<TaskStatusValue, string> = {
  queued: '○',
  running: '◐',
  done: '✓',
  failed: '✗',
};

const STATUS_TITLE: Record<TaskStatusValue, string> = {
  queued: 'queued',
  running: 'running',
  done: 'done',
  failed: 'failed',
};

interface TaskTreeSectionProps {
  board: TaskBoard;
}

export function TaskTreeSection({ board }: TaskTreeSectionProps) {
  const doneCount = board.plan.filter(
    (p) => board.statuses[p.task_id]?.status === 'done',
  ).length;
  const total = board.plan.length;

  return (
    <div className="space-y-1" data-testid="task-tree">
      <div className="text-xs text-text-secondary">子任务 {doneCount}/{total} 完成</div>
      {board.plan.map((item) => {
        const st = board.statuses[item.task_id];
        const status: TaskStatusValue = st?.status ?? 'queued';
        const preview = st?.output_preview ?? st?.error ?? null;
        return (
          <div key={item.task_id} className="flex flex-col gap-1 px-2 py-1 rounded text-xs bg-bg-hover">
            <div className="flex items-center gap-2">
              <span title={STATUS_TITLE[status]} className="w-4 text-center">{STATUS_ICON[status]}</span>
              <span className="px-1 rounded bg-primary/10 text-primary">{item.agent_id}</span>
              <span className="text-text-secondary flex-1">{item.goal}</span>
            </div>
            {preview && status !== 'queued' && (
              <details className="pl-6 text-muted">
                <summary>{status === 'failed' ? '错误详情' : '结果预览'}</summary>
                <pre className="mt-1 whitespace-pre-wrap">{preview}</pre>
              </details>
            )}
          </div>
        );
      })}
    </div>
  );
}
