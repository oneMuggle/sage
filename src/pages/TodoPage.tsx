/**
 * TodoPage - 待办管理页（Task 12 - 2026-09-21 todolist subsystem）。
 *
 * 与侧边栏 TodoSection 的"预览前 5 条 + 链接"互补：这里是完整的待办
 * 管理面板 —— 列表 / 新建 / 完成 / 取消 / 删除。状态走 zustand
 * ``entities/todo/todoStore``，IPC 走 ``shared/api/todoClient``，
 * 组件无业务逻辑副作用，所有副作用委托给 store。
 *
 * 设计取舍：
 * - 不重写表单为受控重组件 —— 输入框仅受控 title，提交后清空；其余
 *   字段（优先级 / 截止时间 / 项目标签）保留后续任务扩展。
 * - 完成 / 取消 / 删除走按钮 + 确认对话框（window.confirm），与
 *   ``Chat`` / ``Memory`` 的删除流一致；调用 store 后 store 自动
 *   重新拉列表。
 * - "暂无待办" 空状态、"加载中" 占位符与 ``Memory.tsx`` 同形态。
 */
import { Check, Loader2, Plus, Trash2, X } from 'lucide-react';
import { useEffect, useState } from 'react';

import { useTodoStore } from '../entities/todo/todoStore';
import type { Todo } from '../shared/api/types';
import { useI18n } from '../shared/lib/i18n';

export function TodoPage() {
  const { t } = useI18n();
  const todos = useTodoStore((s) => s.todos);
  const loading = useTodoStore((s) => s.loading);
  const error = useTodoStore((s) => s.error);
  const load = useTodoStore((s) => s.load);
  const create = useTodoStore((s) => s.create);
  const complete = useTodoStore((s) => s.complete);
  const cancel = useTodoStore((s) => s.cancel);
  const remove = useTodoStore((s) => s.delete);

  const [title, setTitle] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void load();
  }, [load]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = title.trim();
    if (!trimmed) return;
    setBusy(true);
    try {
      await create({ title: trimmed });
      setTitle('');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto p-6 max-w-3xl mx-auto w-full">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-bold">{t('todos.title')}</h1>
      </div>

      <form
        onSubmit={(e) => {
          void handleSubmit(e);
        }}
        className="flex gap-2 mb-4"
        aria-label="新建待办"
      >
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="待办标题..."
          aria-label="待办标题"
          className="flex-1 border border-border rounded-radius-sm px-3 py-2 text-sm bg-surface focus:outline-none focus:border-primary"
        />
        <button
          type="submit"
          disabled={busy || !title.trim()}
          data-testid="todo-submit"
          className="flex items-center gap-1.5 px-3 py-2 bg-primary text-text-inverse text-xs rounded-radius-sm hover:bg-primary-hover disabled:opacity-50"
        >
          <Plus className="w-3.5 h-3.5" />
          添加
        </button>
      </form>

      {error && (
        <div className="mb-4 px-3 py-2 bg-red-50 text-red-700 text-sm rounded" role="alert">
          {error}
        </div>
      )}

      {loading && (
        <div className="flex items-center gap-2 text-text-muted text-sm py-4" role="status">
          <Loader2 className="w-4 h-4 animate-spin" />
          加载中...
        </div>
      )}

      {!loading && todos.length === 0 && (
        <p className="text-text-muted text-center py-8" data-testid="todo-empty">
          {t('todos.empty')}
        </p>
      )}

      {!loading && todos.length > 0 && (
        <ul className="flex flex-col gap-1.5" data-testid="todo-page-list">
          {todos.map((todo) => (
            <TodoRow
              key={todo.id}
              todo={todo}
              onComplete={() => {
                void complete(todo.id);
              }}
              onCancel={() => {
                void cancel(todo.id);
              }}
              onDelete={() => {
                if (window.confirm(`确认删除「${todo.title}」？`)) {
                  void remove(todo.id);
                }
              }}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

interface TodoRowProps {
  todo: Todo;
  onComplete: () => void;
  onCancel: () => void;
  onDelete: () => void;
}

function TodoRow({ todo, onComplete, onCancel, onDelete }: TodoRowProps) {
  const isDone = todo.status === 'completed';
  const isCancelled = todo.status === 'cancelled';
  return (
    <li className="flex items-center justify-between gap-2 px-3 py-2 bg-surface border border-border rounded-radius-sm">
      <div className="flex items-center gap-2 flex-1 min-w-0">
        <span
          className={[
            'text-sm truncate',
            isDone || isCancelled ? 'line-through text-text-muted' : 'text-text',
          ].join(' ')}
        >
          {todo.title}
        </span>
        {todo.priority && todo.priority !== 'medium' && (
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-bg-muted/20 text-text-muted">
            {todo.priority}
          </span>
        )}
      </div>
      <div className="flex items-center gap-1">
        {!isDone && !isCancelled && (
          <>
            <button
              type="button"
              onClick={onComplete}
              title="完成"
              aria-label={`完成 ${todo.title}`}
              className="w-6 h-6 flex items-center justify-center text-text-muted hover:text-green-600 hover:bg-bg-hover rounded"
            >
              <Check className="w-3.5 h-3.5" />
            </button>
            <button
              type="button"
              onClick={onCancel}
              title="取消"
              aria-label={`取消 ${todo.title}`}
              className="w-6 h-6 flex items-center justify-center text-text-muted hover:text-orange-600 hover:bg-bg-hover rounded"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </>
        )}
        <button
          type="button"
          onClick={onDelete}
          title="删除"
          aria-label={`删除 ${todo.title}`}
          className="w-6 h-6 flex items-center justify-center text-text-muted hover:text-red-600 hover:bg-bg-hover rounded"
        >
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      </div>
    </li>
  );
}
