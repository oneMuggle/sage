/**
 * TodoSubtaskTree — Renders todos hierarchically by parent_id.
 *
 * Builds a parent→children map from the flat list and renders top-level
 * items (parent_id == null) with expandable subtask lists. Max 2 levels
 * deep to prevent deeply nested UI.
 */
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useMemo, useState } from 'react';

import type { Todo } from '../../shared/api/types';

interface TodoSubtaskTreeProps {
  todos: Todo[];
  renderTodo: (todo: Todo, depth: number) => React.ReactNode;
}

export function TodoSubtaskTree({ todos, renderTodo }: TodoSubtaskTreeProps) {
  const { topLevel, childrenByParent } = useMemo(() => {
    const childrenMap = new Map<number, Todo[]>();
    const topLevelItems: Todo[] = [];

    for (const todo of todos) {
      if (todo.parent_id != null) {
        const siblings = childrenMap.get(todo.parent_id) ?? [];
        siblings.push(todo);
        childrenMap.set(todo.parent_id, siblings);
      } else {
        topLevelItems.push(todo);
      }
    }

    return { topLevel: topLevelItems, childrenByParent: childrenMap };
  }, [todos]);

  if (topLevel.length === 0 && childrenByParent.size === 0) {
    return null;
  }

  return (
    <ul className="flex flex-col gap-1" data-testid="todo-page-list">
      {topLevel.map((todo) => (
        <TreeNodeItem
          key={todo.id}
          todo={todo}
          childrenByParent={childrenByParent}
          renderTodo={renderTodo}
          depth={0}
        />
      ))}
    </ul>
  );
}

interface TreeNodeItemProps {
  todo: Todo;
  childrenByParent: Map<number, Todo[]>;
  renderTodo: (todo: Todo, depth: number) => React.ReactNode;
  depth: number;
}

function TreeNodeItem({ todo, childrenByParent, renderTodo, depth }: TreeNodeItemProps) {
  const children = childrenByParent.get(todo.id) ?? [];
  const hasChildren = children.length > 0;
  const [expanded, setExpanded] = useState(true);

  const completedCount = children.filter((c) => c.status === 'completed').length;
  const progress = hasChildren ? Math.round((completedCount / children.length) * 100) : 0;

  return (
    <li className="flex flex-col">
      {/* Parent row with expand toggle */}
      <div className="flex items-center">
        {hasChildren && (
          <button
            type="button"
            onClick={() => setExpanded(!expanded)}
            className="w-5 h-5 flex items-center justify-center text-text-muted hover:text-text flex-shrink-0"
            aria-label={expanded ? '收起子任务' : '展开子任务'}
            aria-expanded={expanded}
          >
            {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
          </button>
        )}
        <div className={hasChildren ? 'flex-1' : 'flex-1 ml-5'}>{renderTodo(todo, depth)}</div>
      </div>

      {/* Progress bar for parent with children */}
      {hasChildren && (
        <div className="ml-8 mr-3 h-1 bg-bg-muted rounded-full overflow-hidden">
          <div
            className="h-full bg-primary transition-all duration-300"
            style={{ width: `${progress}%` }}
          />
        </div>
      )}

      {/* Children (max 2 levels) */}
      {hasChildren && expanded && depth < 2 && (
        <ul className="ml-8 mt-1 flex flex-col gap-0.5 border-l border-border/50 pl-2">
          {children.map((child) => {
            const grandchildren = childrenByParent.get(child.id) ?? [];
            const hasGrandchildren = grandchildren.length > 0;

            return (
              <li key={child.id} className="flex flex-col">
                <div className="flex items-center">
                  {hasGrandchildren && depth < 1 && (
                    <button
                      type="button"
                      className="w-4 h-4 flex items-center justify-center text-text-muted flex-shrink-0"
                      aria-hidden
                    >
                      <ChevronRight className="w-2.5 h-2.5" />
                    </button>
                  )}
                  <div className={hasGrandchildren && depth < 1 ? 'flex-1' : 'flex-1 ml-4'}>
                    {renderTodo(child, depth + 1)}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </li>
  );
}
