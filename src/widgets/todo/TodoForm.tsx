import { useState } from 'react';
import type { FormEvent } from 'react';

import { useTodoStore } from '../../entities/todo/todoStore';
import type { TodoPriority } from '../../shared/api/types';

export function TodoForm() {
  const create = useTodoStore((s) => s.create);
  const [title, setTitle] = useState('');
  const [priority, setPriority] = useState<TodoPriority>('medium');
  const [dueAt, setDueAt] = useState('');

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const trimmed = title.trim();
    if (!trimmed) return;
    await create({
      title: trimmed,
      priority,
      due_at: dueAt || undefined,
    });
    setTitle('');
    setDueAt('');
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="flex flex-col gap-2 p-3 border border-border rounded-radius-sm"
    >
      <input
        type="text"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="New todo…"
        className="px-2 py-1 text-sm border border-border rounded"
      />
      <div className="flex gap-2">
        <select
          value={priority}
          onChange={(e) => setPriority(e.target.value as TodoPriority)}
          className="px-2 py-1 text-xs border border-border rounded"
        >
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
        <input
          type="datetime-local"
          value={dueAt}
          onChange={(e) => setDueAt(e.target.value)}
          className="px-2 py-1 text-xs border border-border rounded"
        />
      </div>
      <button
        type="submit"
        disabled={!title.trim()}
        className="px-3 py-1 text-sm bg-primary text-white rounded hover:bg-primary/90 disabled:opacity-50"
      >
        Add
      </button>
    </form>
  );
}