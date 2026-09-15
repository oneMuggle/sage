// src/widgets/chat/progress/TodoListSection.tsx
// P1 todo 接线 (2026-08-21): agent 自维护任务清单卡片。
// 数据源 = todo_snapshot SSE 全量快照（store.todos）。
// PR-C (2026-08-22): 编排计划单向镜像 —— 纯前端派生自 taskBoard，
// 与 agent 自建 todos 共存；todo_write 天然无法篡改镜像项（不同数据源）。
import type { TaskBoard } from '../../../features/send-message/useChat';
import type { TaskStatusValue, TodoItem } from '../../../shared/api';

const GLYPH: Record<TodoItem['status'], string> = {
  pending: '○',
  in_progress: '◐',
  completed: '☑',
};

const ORCH_GLYPH: Record<TaskStatusValue, string> = {
  queued: '○',
  running: '◐',
  done: '☑',
  failed: '✗',
  cancelled: '⊘',
};

const ORCH_LABEL: Record<TaskStatusValue, string> = {
  queued: '等待中',
  running: '进行中',
  done: '已完成',
  failed: '失败',
  cancelled: '已取消',
};

/** 编排状态 → 字形/中文标签。 */
function mapOrchStatus(status: TaskStatusValue) {
  return { glyph: ORCH_GLYPH[status], label: ORCH_LABEL[status] };
}

interface TodoListSectionProps {
  todos: TodoItem[];
  /** PR-C: 编排任务板（null/缺省 = 无编排，不渲染镜像区）。 */
  taskBoard?: TaskBoard | null;
}

export function TodoListSection({ todos, taskBoard }: TodoListSectionProps) {
  if (todos.length === 0 && !(taskBoard && taskBoard.plan.length > 0)) return null;
  const done = todos.filter((t) => t.status === 'completed').length;

  return (
    <div className="space-y-1" data-testid="todo-list">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-text-secondary">任务清单</span>
        <span className="text-xs text-text-secondary" data-testid="todo-progress">
          {done}/{todos.length}
        </span>
      </div>
      {todos.map((item, i) => (
        <div
          key={`${i}-${item.content}`}
          data-testid={`todo-item-${i}`}
          className="flex items-center gap-2 px-2 py-1 rounded text-xs bg-bg-hover"
        >
          <span className="w-4 text-center">{GLYPH[item.status]}</span>
          <span
            className={
              item.status === 'completed'
                ? 'text-text-tertiary line-through flex-1'
                : 'text-text-secondary flex-1'
            }
          >
            {item.content}
          </span>
          {item.status === 'in_progress' && item.activeForm && (
            <span className="text-primary shrink-0">{item.activeForm}</span>
          )}
        </div>
      ))}
      {taskBoard && taskBoard.plan.length > 0 && (
        <>
          <div className="text-xs font-medium text-text-secondary pt-1">编排计划</div>
          {taskBoard.plan.map((item) => {
            const status: TaskStatusValue = taskBoard.statuses[item.task_id]?.status ?? 'queued';
            const { glyph, label } = mapOrchStatus(status);
            return (
              <div
                key={item.task_id}
                data-testid={`todo-mirror-${item.task_id}`}
                className={`flex items-center gap-2 px-2 py-1 rounded text-xs bg-bg-hover ${
                  (item.depends_on?.length ?? 0) > 0 ? 'ml-4' : ''
                }`}
              >
                <span className="w-4 text-center">{glyph}</span>
                <span className="px-1 rounded bg-primary/10 text-primary shrink-0">编排</span>
                <span className="text-text-secondary flex-1">{item.goal}</span>
                <span className="text-text-tertiary shrink-0">{label}</span>
              </div>
            );
          })}
        </>
      )}
    </div>
  );
}
