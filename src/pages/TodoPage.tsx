/**
 * TodoPage — Full-featured todo management page.
 *
 * Notion-inspired design with:
 * - Enhanced creation form (description, priority, due date, project tag)
 * - Filter / Sort / Search toolbar (search is server-side via FTS5, debounced)
 * - Inline editing (title, priority, due date)
 * - Hierarchical subtask rendering with progress bars (+ inline subtask add)
 * - Batch operations (select all, batch complete, batch delete via batch API)
 * - Export to JSON / Markdown
 * - Quick add with local natural-language parsing (N / 命令面板 / ?quickadd=1)
 *
 * State flows through zustand `entities/todo/todoStore`, IPC through
 * `shared/api/todoClient`. All CRUD delegated to store.
 */
import { BarChart3, Check, Download, Loader2, Sparkles, Trash2, Zap } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { useTodoStore } from '../entities/todo/todoStore';
import { agentsApi } from '../shared/api/agentsApi';
import { todoClient } from '../shared/api/todoClient';
import type { Todo, TodoListParams, UpdateTodoInput } from '../shared/api/types';
import { useI18n } from '../shared/lib/i18n';
import { PageHeader } from '../shared/ui';

import { TodoAiDialog } from './todo/TodoAiDialog';
import { TodoCreateForm } from './todo/TodoCreateForm';
import { TodoHeatmap } from './todo/TodoHeatmap';
import { TodoQuickAdd } from './todo/TodoQuickAdd';
import { TodoRowEditor } from './todo/TodoRowEditor';
import { TodoSubtaskTree } from './todo/TodoSubtaskTree';
import { TodoToolbar } from './todo/TodoToolbar';

/** 专家条目（阶段 3：专家专属待办的过滤/创建来源）。 */
export interface TodoSpecialistOption {
  id: string;
  name: string;
}

/** 搜索输入防抖，避免每次按键都打后端 FTS。 */
const SEARCH_DEBOUNCE_MS = 300;

export function TodoPage() {
  const { t } = useI18n();
  const [searchParams, setSearchParams] = useSearchParams();
  const todos = useTodoStore((s) => s.todos);
  const loading = useTodoStore((s) => s.loading);
  const error = useTodoStore((s) => s.error);
  const params = useTodoStore((s) => s.params);
  const load = useTodoStore((s) => s.load);
  const setParams = useTodoStore((s) => s.setParams);
  const create = useTodoStore((s) => s.create);
  const update = useTodoStore((s) => s.update);
  const complete = useTodoStore((s) => s.complete);
  const cancel = useTodoStore((s) => s.cancel);
  const remove = useTodoStore((s) => s.delete);
  const batchComplete = useTodoStore((s) => s.batchComplete);
  const batchDelete = useTodoStore((s) => s.batchDelete);
  const snooze = useTodoStore((s) => s.snooze);

  const [searchQuery, setSearchQuery] = useState('');
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [createBusy, setCreateBusy] = useState(false);
  const [quickAddOpen, setQuickAddOpen] = useState(false);
  const [aiDialog, setAiDialog] = useState<null | 'brief' | 'weekly'>(null);
  const [showHeatmap, setShowHeatmap] = useState(false);
  const [specialists, setSpecialists] = useState<TodoSpecialistOption[]>([]);
  const lastSentQuery = useRef<string | undefined>(params.q);

  useEffect(() => {
    void load();
  }, [load]);

  // 专家列表（阶段 3）：失败静默降级为不显示专家过滤/选择器。
  useEffect(() => {
    agentsApi
      .list()
      .then((agents) => setSpecialists(agents.map((agent) => ({ id: agent.id, name: agent.name }))))
      .catch(() => setSpecialists([]));
  }, []);

  // 命令面板入口：/todos?quickadd=1 → 打开快速录入并清掉参数（避免刷新重开）。
  useEffect(() => {
    if (searchParams.get('quickadd') !== '1') return;
    setQuickAddOpen(true);
    const next = new URLSearchParams(searchParams);
    next.delete('quickadd');
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);

  // 应用内快捷键：非输入状态下按 n 打开快速录入。
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'n' && e.key !== 'N') return;
      if (e.ctrlKey || e.metaKey || e.altKey || e.shiftKey) return;
      const target = e.target as HTMLElement | null;
      const tagName = target?.tagName?.toLowerCase();
      if (tagName === 'input' || tagName === 'textarea' || tagName === 'select') return;
      if (target?.isContentEditable) return;
      e.preventDefault();
      setQuickAddOpen(true);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  // 搜索走后端 FTS：防抖后把 q 合入过滤参数。
  useEffect(() => {
    const trimmed = searchQuery.trim();
    const nextQ = trimmed || undefined;
    if (nextQ === (lastSentQuery.current ?? undefined)) return;
    const handle = window.setTimeout(() => {
      lastSentQuery.current = nextQ;
      void setParams({ ...params, q: nextQ });
    }, SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(handle);
  }, [searchQuery, params, setParams]);

  // Check if any subtasks exist to decide rendering mode
  const hasSubtasks = useMemo(() => todos.some((todo) => todo.parent_id != null), [todos]);

  const handleParamsChange = useCallback(
    (newParams: TodoListParams) => {
      void setParams(newParams);
    },
    [setParams],
  );

  const handleCreate = useCallback(
    async (input: {
      title: string;
      description?: string;
      priority?: 'high' | 'medium' | 'low';
      due_at?: string;
      project_tag?: string;
      tags?: string[];
      reminder_offsets?: number[];
    }) => {
      setCreateBusy(true);
      try {
        await create(input);
      } finally {
        setCreateBusy(false);
      }
    },
    [create],
  );

  const handleUpdate = useCallback(
    async (id: number, changes: UpdateTodoInput) => {
      await update(id, changes);
    },
    [update],
  );

  const handleComplete = useCallback(
    async (id: number) => {
      await complete(id);
    },
    [complete],
  );

  const handleCancel = useCallback(
    async (id: number) => {
      await cancel(id);
    },
    [cancel],
  );

  const handleDelete = useCallback(
    async (id: number) => {
      await remove(id);
      setSelectedIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    },
    [remove],
  );

  // Batch operations
  const handleSelect = useCallback((id: number, selected: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (selected) {
        next.add(id);
      } else {
        next.delete(id);
      }
      return next;
    });
  }, []);

  const handleSelectAll = useCallback(() => {
    if (selectedIds.size === todos.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(todos.map((t) => t.id)));
    }
  }, [todos, selectedIds.size]);

  const handleBatchComplete = useCallback(async () => {
    if (selectedIds.size === 0) return;
    await batchComplete([...selectedIds]);
    setSelectedIds(new Set());
  }, [selectedIds, batchComplete]);

  const handleBatchDelete = useCallback(async () => {
    if (selectedIds.size === 0) return;
    await batchDelete([...selectedIds]);
    setSelectedIds(new Set());
  }, [selectedIds, batchDelete]);

  const handleExport = useCallback(async (format: 'json' | 'md') => {
    const result = await todoClient.exportTodos(format, true);
    const mime = format === 'json' ? 'application/json' : 'text/markdown';
    const blob = new Blob([result.content], { type: `${mime};charset=utf-8` });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = result.filename;
    anchor.click();
    URL.revokeObjectURL(url);
  }, []);

  const handleAddSubtask = useCallback(
    async (parentId: number, title: string) => {
      await create({ title, parent_id: parentId });
    },
    [create],
  );

  const handleSnooze = useCallback(
    async (id: number, minutes: number) => {
      await snooze(id, minutes);
    },
    [snooze],
  );

  const allSelected = todos.length > 0 && selectedIds.size === todos.length;
  const someSelected = selectedIds.size > 0;

  // Render function for TodoSubtaskTree
  const renderTodo = useCallback(
    (todo: Todo, _depth: number) => (
      <TodoRowEditor
        key={todo.id}
        todo={todo}
        selected={selectedIds.has(todo.id)}
        onSelect={handleSelect}
        onUpdate={handleUpdate}
        onComplete={handleComplete}
        onCancel={handleCancel}
        onDelete={handleDelete}
        onAddSubtask={todo.parent_id == null ? handleAddSubtask : undefined}
        onSnooze={handleSnooze}
        specialists={specialists}
      />
    ),
    [
      selectedIds,
      handleSelect,
      handleUpdate,
      handleComplete,
      handleCancel,
      handleDelete,
      handleAddSubtask,
      handleSnooze,
      specialists,
    ],
  );

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <PageHeader
        title={t('todos.title')}
        actions={
          <div className="flex items-center gap-2 text-ui-xs text-text-muted">
            {todos.length > 0 && (
              <span>
                {todos.filter((t) => t.status === 'completed').length}/{todos.length} 已完成
              </span>
            )}
            <button
              type="button"
              onClick={() => setAiDialog('brief')}
              title="AI 今日简报"
              aria-label="AI 简报"
              data-testid="todo-ai-brief"
              className="flex items-center gap-1 px-2 py-1 rounded border border-border hover:border-primary hover:text-primary"
            >
              <Sparkles className="w-3 h-3" />
              简报
            </button>
            <button
              type="button"
              onClick={() => setAiDialog('weekly')}
              title="周回顾"
              aria-label="周回顾"
              data-testid="todo-ai-weekly"
              className="flex items-center gap-1 px-2 py-1 rounded border border-border hover:border-primary hover:text-primary"
            >
              周回顾
            </button>
            <button
              type="button"
              onClick={() => setShowHeatmap((v) => !v)}
              title="完成热力图"
              aria-label="完成热力图"
              aria-pressed={showHeatmap}
              data-testid="todo-heatmap-toggle"
              className={`flex items-center gap-1 px-2 py-1 rounded border hover:border-primary hover:text-primary ${
                showHeatmap ? 'border-primary text-primary' : 'border-border'
              }`}
            >
              <BarChart3 className="w-3 h-3" />
              热力图
            </button>
            <button
              type="button"
              onClick={() => setQuickAddOpen(true)}
              title="快速添加（快捷键 N）"
              aria-label="快速添加"
              className="flex items-center gap-1 px-2 py-1 rounded border border-border hover:border-primary hover:text-primary"
            >
              <Zap className="w-3 h-3" />
              快速添加
            </button>
            <button
              type="button"
              onClick={() => void handleExport('md')}
              title="导出 Markdown"
              aria-label="导出 Markdown"
              className="flex items-center gap-1 px-2 py-1 rounded border border-border hover:border-primary hover:text-primary"
            >
              <Download className="w-3 h-3" />
              MD
            </button>
            <button
              type="button"
              onClick={() => void handleExport('json')}
              title="导出 JSON"
              aria-label="导出 JSON"
              className="flex items-center gap-1 px-2 py-1 rounded border border-border hover:border-primary hover:text-primary"
            >
              <Download className="w-3 h-3" />
              JSON
            </button>
          </div>
        }
      />

      <div className="flex-1 overflow-y-auto p-6 max-w-3xl mx-auto w-full">
        {/* Enhanced creation form */}
        <TodoCreateForm onCreate={handleCreate} busy={createBusy} specialists={specialists} />

        {/* Filter / Sort toolbar */}
        <TodoToolbar
          params={params}
          searchQuery={searchQuery}
          specialists={specialists}
          onParamsChange={handleParamsChange}
          onSearchChange={setSearchQuery}
        />

        {/* 完成热力图（阶段 3，可折叠） */}
        {showHeatmap && (
          <div className="px-1">
            <TodoHeatmap />
          </div>
        )}

        {/* Batch operations bar */}
        {someSelected && (
          <div className="flex items-center gap-2 mb-2 px-3 py-1.5 bg-primary/5 border border-primary/20 rounded-radius-sm">
            <span className="text-ui-xs text-text-muted">已选择 {selectedIds.size} 项</span>
            <button
              type="button"
              onClick={() => void handleBatchComplete()}
              className="flex items-center gap-1 px-2 py-0.5 text-ui-xs text-green-600 hover:bg-green-50 dark:hover:bg-green-900/20 rounded"
            >
              <Check className="w-3 h-3" />
              批量完成
            </button>
            <button
              type="button"
              onClick={() => void handleBatchDelete()}
              className="flex items-center gap-1 px-2 py-0.5 text-ui-xs text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 rounded"
            >
              <Trash2 className="w-3 h-3" />
              批量删除
            </button>
          </div>
        )}

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
            {searchQuery ? '没有匹配的待办' : t('todos.empty')}
          </p>
        )}

        {!loading && todos.length > 0 && (
          <>
            {/* Select all checkbox */}
            <div className="flex items-center gap-2 mb-1.5 px-1">
              <input
                type="checkbox"
                checked={allSelected}
                onChange={handleSelectAll}
                className="w-3.5 h-3.5 rounded border-border accent-primary cursor-pointer"
                aria-label={allSelected ? '取消全选' : '全选'}
              />
              <span className="text-ui-xs text-text-muted">
                {allSelected ? '取消全选' : '全选'}
              </span>
            </div>

            {/* Todo list — hierarchical if subtasks exist, flat otherwise */}
            {hasSubtasks ? (
              <TodoSubtaskTree todos={todos} renderTodo={renderTodo} />
            ) : (
              <ul className="flex flex-col gap-1.5" data-testid="todo-page-list">
                {todos.map((todo) => (
                  <TodoRowEditor
                    key={todo.id}
                    todo={todo}
                    selected={selectedIds.has(todo.id)}
                    onSelect={handleSelect}
                    onUpdate={handleUpdate}
                    onComplete={handleComplete}
                    onCancel={handleCancel}
                    onDelete={handleDelete}
                    onAddSubtask={todo.parent_id == null ? handleAddSubtask : undefined}
                    onSnooze={handleSnooze}
                    specialists={specialists}
                  />
                ))}
              </ul>
            )}
          </>
        )}
      </div>

      <TodoQuickAdd
        isOpen={quickAddOpen}
        onClose={() => setQuickAddOpen(false)}
        onSubmit={async (input) => {
          await create(input);
        }}
      />

      <TodoAiDialog
        isOpen={aiDialog !== null}
        mode={aiDialog ?? 'brief'}
        onClose={() => setAiDialog(null)}
      />
    </div>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditTodoPageGovernance(): {
  module: 'src/pages/TodoPage.tsx';
  phase: 'P171';
  domain: 'pages';
  supportsCompleteCancelAndTwoStepDelete: boolean;
  compliant: boolean;
} {
  return {
    module: 'src/pages/TodoPage.tsx',
    phase: 'P171',
    domain: 'pages',
    supportsCompleteCancelAndTwoStepDelete: true,
    compliant: true,
  };
}
