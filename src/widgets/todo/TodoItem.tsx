import { Check, Trash2 } from 'lucide-react';

import { useTodoStore } from '../../entities/todo/todoStore';
import type { Todo } from '../../shared/api/types';

interface TodoItemProps {
  todo: Todo;
}

export function TodoItem({ todo }: TodoItemProps) {
  const complete = useTodoStore((s) => s.complete);
  const remove = useTodoStore((s) => s.delete);

  const urgencyColor = {
    critical: 'text-red-600',
    urgent: 'text-orange-500',
    normal: 'text-text',
  }[todo.effective_urgency ?? 'normal'];

  return (
    <div className="flex items-center gap-2 px-3 py-2 hover:bg-bg-hover rounded-radius-sm">
      <button
        onClick={() => void complete(todo.id)}
        className="w-5 h-5 rounded-full border border-border hover:bg-success/10 flex items-center justify-center"
        aria-label="Mark complete"
      >
        <Check className="w-3 h-3" />
      </button>
      <div className="flex-1 min-w-0">
        <div className={`text-sm truncate ${urgencyColor}`}>{todo.title}</div>
        {todo.due_at && (
          <div className="text-[10px] text-text-muted">
            Due {new Date(todo.due_at).toLocaleDateString()}
          </div>
        )}
      </div>
      <span
        className={`text-[10px] px-1.5 py-0.5 rounded-full ${
          todo.priority === 'high'
            ? 'bg-red-100 text-red-700'
            : todo.priority === 'medium'
              ? 'bg-yellow-100 text-yellow-700'
              : 'bg-gray-100 text-gray-700'
        }`}
      >
        {todo.priority}
      </span>
      {todo.is_recurring && <span title="Recurring">🔄</span>}
      <button
        onClick={() => void remove(todo.id)}
        className="opacity-0 group-hover:opacity-100 text-text-muted hover:text-red-600"
        aria-label="Delete"
      >
        <Trash2 className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}