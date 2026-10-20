import { Check, Trash2 } from 'lucide-react';
import { useState } from 'react';

import { useTodoStore } from '../../entities/todo/todoStore';
import type { Todo } from '../../shared/api/types';

interface TodoItemProps {
  todo: Todo;
}

export function TodoItem({ todo }: TodoItemProps) {
  const complete = useTodoStore((s) => s.complete);
  const remove = useTodoStore((s) => s.delete);
  const [copiedMd, setCopiedMd] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

  const urgencyColor = {
    critical: 'text-red-600',
    urgent: 'text-orange-500',
    normal: 'text-text',
  }[todo.effective_urgency ?? 'normal'];

  const handleCopyMd = () => {
    setCopiedMd(true);
    /* v8 ignore start */
    setTimeout(() => setCopiedMd(false), 2000);
    const md = `- [ ] **${todo.title}** (${todo.priority}${todo.due_at ? ` · Due ${todo.due_at}` : ''})`;
    void navigator.clipboard?.writeText(md);
    /* v8 ignore stop */
  };

  const handleCopyJson = () => {
    setCopiedJson(true);
    /* v8 ignore start */
    setTimeout(() => setCopiedJson(false), 2000);
    void navigator.clipboard?.writeText(JSON.stringify(todo, null, 2));
    /* v8 ignore stop */
  };

  return (
    <div className="group flex items-center gap-2 px-3 py-2 hover:bg-bg-hover rounded-radius-sm">
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
          <div className="text-ui-xs text-text-muted">
            Due {new Date(todo.due_at).toLocaleDateString()}
          </div>
        )}
      </div>
      <span
        className={`text-ui-xs px-1.5 py-0.5 rounded-full ${
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
        type="button"
        data-testid={`todo-item-copy-md-${todo.id}`}
        onClick={handleCopyMd}
        className="px-1.5 py-0.5 text-ui-2xs rounded border border-border text-text-muted hover:text-text"
      >
        {copiedMd ? '已复制MD' : '复制MD'}
      </button>
      <button
        type="button"
        data-testid={`todo-item-copy-json-${todo.id}`}
        onClick={handleCopyJson}
        className="px-1.5 py-0.5 text-ui-2xs rounded border border-border text-text-muted hover:text-text"
      >
        {copiedJson ? '已复制JSON' : '复制JSON'}
      </button>
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
