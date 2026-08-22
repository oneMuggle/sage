// src/widgets/chat/progress/TodoListSection.tsx
// P1 todo 接线 (2026-08-21): agent 自维护任务清单卡片。
// 数据源 = todo_snapshot SSE 全量快照（store.todos）；编排镜像见 PR-C。
import type { TodoItem } from '../../../shared/api';

const GLYPH: Record<TodoItem['status'], string> = {
  pending: '○',
  in_progress: '◐',
  completed: '☑',
};

interface TodoListSectionProps {
  todos: TodoItem[];
}

export function TodoListSection({ todos }: TodoListSectionProps) {
  if (todos.length === 0) return null;
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
    </div>
  );
}
