import { ListTodo, Plus } from 'lucide-react';
import { useEffect } from 'react';
import { Link } from 'react-router-dom';

import { useTodoStore } from '../../../entities/todo/todoStore';
import { useI18n } from '../../../shared/lib/i18n';
import { SiderSection } from '../SiderSection';

interface TodoSectionProps {
  collapsed: boolean;
  onToggleCollapsed: () => void;
}

export function TodoSection({ collapsed, onToggleCollapsed }: TodoSectionProps) {
  const { t } = useI18n();
  const todos = useTodoStore((s) => s.todos);
  const load = useTodoStore((s) => s.load);

  useEffect(() => {
    void load();
  }, [load]);

  const pendingCount = todos.filter(
    (todo) => todo.status === 'pending' || todo.status === 'in_progress',
  ).length;

  return (
    <SiderSection
      sectionKey="todos"
      // sidebar label is decoupled from `todos.title` (used by TodoPage H1) so the
      // sidebar entry stays a single short word "待办" matching `sider.section.*` siblings.
      label={t('sider.section.todos')}
      icon={ListTodo}
      collapsed={collapsed}
      onToggleCollapsed={onToggleCollapsed}
      trailing={
        <Link
          to="/todos"
          title={t('todos.create')}
          aria-label={t('todos.create')}
          className="w-5 h-5 flex items-center justify-center rounded text-text-muted hover:text-text hover:bg-bg-hover"
        >
          <Plus className="w-3.5 h-3.5" />
        </Link>
      }
      render={() => (
        <ul className="flex flex-col" data-testid="todo-list">
          {pendingCount === 0 && (
            <li className="text-[11px] text-text-muted px-2 py-1 italic">{t('todos.empty')}</li>
          )}
          {todos.slice(0, 5).map((todo) => (
            <li
              key={todo.id}
              className="group flex items-center justify-between gap-2 px-2 py-1 rounded-radius-sm hover:bg-bg-hover"
            >
              <span className="text-xs text-text truncate">{todo.title}</span>
              <span
                className={[
                  'text-[10px] px-1.5 py-0.5 rounded-full flex-shrink-0',
                  todo.effective_urgency === 'critical'
                    ? 'bg-red-100 text-red-700'
                    : todo.effective_urgency === 'urgent'
                      ? 'bg-orange-100 text-orange-700'
                      : 'bg-bg-muted/20 text-text-muted',
                ].join(' ')}
              >
                {todo.effective_urgency ?? 'normal'}
              </span>
            </li>
          ))}
        </ul>
      )}
    />
  );
}
