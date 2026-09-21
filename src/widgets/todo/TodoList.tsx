import { useEffect } from 'react';

import { useTodoStore } from '../../entities/todo/todoStore';

import { TodoItem } from './TodoItem';

export function TodoList() {
  const todos = useTodoStore((s) => s.todos);
  const loading = useTodoStore((s) => s.loading);
  const load = useTodoStore((s) => s.load);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return <div className="text-sm text-text-muted p-4">Loading…</div>;
  }
  if (todos.length === 0) {
    return <div className="text-sm text-text-muted p-4 italic">No todos yet</div>;
  }

  return (
    <div className="flex flex-col gap-1">
      {todos.map((todo) => (
        <TodoItem key={todo.id} todo={todo} />
      ))}
    </div>
  );
}
