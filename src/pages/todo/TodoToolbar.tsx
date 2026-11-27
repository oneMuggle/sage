/**
 * TodoToolbar — Filter / Sort controls for TodoPage.
 *
 * Notion-style toolbar: search + smart view segmented control + tag filter +
 * priority filter + sort dropdown. Changes immediately dispatch to parent via
 * onParamsChange callback.
 */
import { Filter, Search, SortAsc, SortDesc } from 'lucide-react';
import { useEffect, useState } from 'react';

import { todoClient } from '../../shared/api/todoClient';
import type { TodoListParams, TodoPriority, TodoTagCount } from '../../shared/api/types';

interface TodoToolbarProps {
  params: TodoListParams;
  searchQuery: string;
  /** 阶段 3：可选专家列表（专家过滤）；空/未提供时不显示过滤。 */
  specialists?: Array<{ id: string; name: string }>;
  onParamsChange: (params: TodoListParams) => void;
  onSearchChange: (query: string) => void;
}

type TodoView = NonNullable<TodoListParams['view']>;

const VIEW_OPTIONS: Array<{ value: TodoView; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'today', label: '今天' },
  { value: 'week', label: '近7天' },
  { value: 'completed', label: '已完成' },
];

const PRIORITY_OPTIONS: Array<{ value: TodoPriority | ''; label: string }> = [
  { value: '', label: '全部优先级' },
  { value: 'high', label: '🔴 高' },
  { value: 'medium', label: '🟡 中' },
  { value: 'low', label: '🟢 低' },
];

/**
 * 状态筛选。
 *
 * 与智能视图互斥：后端 ``todo_filters`` 里 ``view`` 优先于 ``status``，
 * 两者同时传时状态筛选会静默失效 —— 所以切状态要清掉 ``view``，切视图要
 * 清掉 ``status``。
 *
 * ``all`` 是后端认的「含已完成/已取消」的逃逸口（router 会把它翻译成
 * ``include_completed=True``）；空串 = 不加状态条件，沿用当前视图语义。
 */
const STATUS_OPTIONS: Array<{ value: string; label: string }> = [
  { value: '', label: '不限状态' },
  { value: 'pending', label: '未开始' },
  { value: 'in_progress', label: '进行中' },
  { value: 'completed', label: '已完成' },
  { value: 'cancelled', label: '已取消' },
  { value: 'all', label: '全部（含已完成）' },
];

/**
 * 排序依据。
 *
 * ``manual``（手动排序）是默认项 —— 拖拽排序只有在手工序下才有意义，
 * 选其他排序时拖柄会禁用并提示原因（见 ``TodoRowEditor`` 的拖柄）。
 */
const SORT_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'manual', label: '手动排序' },
  { value: 'created_at', label: '创建时间' },
  { value: 'due_at', label: '截止日期' },
  { value: 'priority', label: '优先级' },
];

export function TodoToolbar({
  params,
  searchQuery,
  specialists = [],
  onParamsChange,
  onSearchChange,
}: TodoToolbarProps) {
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>(params.sort_order ?? 'asc');
  const [tagOptions, setTagOptions] = useState<TodoTagCount[]>([]);

  // 标签清单来自后端聚合（失败静默降级为不显示标签过滤）。
  useEffect(() => {
    todoClient
      .listTags()
      .then(setTagOptions)
      .catch(() => setTagOptions([]));
  }, []);

  const handleViewChange = (view: TodoView) => {
    const next: TodoListParams = { ...params, view };
    delete next.status;
    delete next.include_completed;
    onParamsChange(next);
  };

  const handleTagChange = (tag: string) => {
    const next: TodoListParams = { ...params, tag: tag || undefined };
    onParamsChange(next);
  };

  const handleSpecialistChange = (specialistId: string) => {
    const next: TodoListParams = {
      ...params,
      specialist_id: specialistId || undefined,
    };
    onParamsChange(next);
  };

  const handlePriorityChange = (priority: TodoPriority | '') => {
    const next: TodoListParams = { ...params, priority: priority || undefined };
    onParamsChange(next);
  };

  /**
   * 状态筛选：与智能视图互斥。
   *
   * 后端 ``todo_filters`` 里 ``view`` 的优先级高于 ``status``，两个都传时
   * 状态条件会被 view 分支吃掉（表现为「选了没反应」）。所以这里必须清掉
   * ``view`` / ``include_completed``，反之 ``handleViewChange`` 清掉
   * ``status``。
   */
  const handleStatusChange = (status: string) => {
    const next: TodoListParams = { ...params };
    if (status) {
      next.status = status;
    } else {
      delete next.status;
    }
    delete next.view;
    delete next.include_completed;
    onParamsChange(next);
  };

  const handleSortChange = (sortBy: string) => {
    const next: TodoListParams = {
      ...params,
      sort_by: (sortBy as TodoListParams['sort_by']) || undefined,
      sort_order: sortOrder,
    };
    onParamsChange(next);
  };

  const toggleSortOrder = () => {
    const nextOrder = sortOrder === 'asc' ? 'desc' : 'asc';
    setSortOrder(nextOrder);
    if (params.sort_by) {
      onParamsChange({ ...params, sort_order: nextOrder });
    }
  };

  // 状态筛选生效时没有智能视图可言 —— 让视图按钮组全部呈现未选中，
  // 免得「已完成」按钮高亮着而列表其实是按 status 筛的。
  const activeView: TodoView | null = params.view ?? (params.status ? null : 'all');
  // 「手动排序」是默认排序，不算「有筛选条件」—— 否则清除按钮永远显示。
  const hasFilters =
    Boolean(params.priority) ||
    (Boolean(params.sort_by) && params.sort_by !== 'manual') ||
    Boolean(params.tag) ||
    Boolean(params.status) ||
    params.view !== undefined;

  /**
   * 清除筛选。
   *
   * 排序基准要显式回到「手动排序」—— 若把 ``sort_by`` 一起清掉，服务端会退回
   * 默认的 ``due_at``，拖柄随之失效（只有手工序才允许拖拽排序）。
   */
  const clearFilters = () => {
    setSortOrder('asc');
    onParamsChange({ sort_by: 'manual' });
    onSearchChange('');
  };

  return (
    <div className="flex flex-wrap items-center gap-2 px-1 py-2">
      {/* Search */}
      <div className="relative flex-1 min-w-[160px] max-w-xs">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-text-muted pointer-events-none" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="搜索待办..."
          aria-label="搜索待办"
          className="w-full pl-8 pr-3 py-1.5 text-xs border border-border rounded-radius-sm bg-surface focus:outline-none focus:border-primary placeholder:text-text-muted"
        />
      </div>

      {/* Smart views */}
      <div
        className="flex items-center rounded-radius-sm border border-border overflow-hidden"
        role="group"
        aria-label="智能视图"
      >
        {VIEW_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            type="button"
            onClick={() => handleViewChange(opt.value)}
            aria-pressed={activeView === opt.value}
            className={`px-2 py-1.5 text-xs transition-colors ${
              activeView === opt.value
                ? 'bg-primary/10 text-primary'
                : 'text-text-muted hover:text-text hover:bg-bg-hover/40'
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* Tag filter（无标签时不显示） */}
      {tagOptions.length > 0 && (
        <select
          value={params.tag ?? ''}
          onChange={(e) => handleTagChange(e.target.value)}
          aria-label="按标签过滤"
          className="rounded-radius-sm border border-border bg-surface px-2 py-1.5 text-xs text-text focus:outline-none focus:border-primary"
        >
          <option value="">全部标签</option>
          {tagOptions.map((opt) => (
            <option key={opt.tag} value={opt.tag}>
              #{opt.tag}（{opt.count}）
            </option>
          ))}
        </select>
      )}

      {/* 专家过滤（阶段 3；无专家时不显示） */}
      {specialists.length > 0 && (
        <select
          value={params.specialist_id ?? ''}
          onChange={(e) => handleSpecialistChange(e.target.value)}
          aria-label="按专家过滤"
          data-testid="todo-specialist-filter"
          className="rounded-radius-sm border border-border bg-surface px-2 py-1.5 text-xs text-text focus:outline-none focus:border-primary"
        >
          <option value="">全部专家</option>
          {specialists.map((specialist) => (
            <option key={specialist.id} value={specialist.id}>
              {specialist.name}
            </option>
          ))}
        </select>
      )}

      {/* Priority filter */}
      <select
        value={params.priority ?? ''}
        onChange={(e) => handlePriorityChange(e.target.value as TodoPriority | '')}
        aria-label="按优先级过滤"
        className="rounded-radius-sm border border-border bg-surface px-2 py-1.5 text-xs text-text focus:outline-none focus:border-primary"
      >
        {PRIORITY_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>

      {/* Status filter（与智能视图互斥） */}
      <select
        value={params.status ?? ''}
        onChange={(e) => handleStatusChange(e.target.value)}
        aria-label="按状态过滤"
        data-testid="todo-status-filter"
        className="rounded-radius-sm border border-border bg-surface px-2 py-1.5 text-xs text-text focus:outline-none focus:border-primary"
      >
        {STATUS_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>

      {/* Sort */}
      <div className="flex items-center gap-0.5">
        <select
          value={params.sort_by ?? ''}
          onChange={(e) => handleSortChange(e.target.value)}
          aria-label="排序依据"
          className="rounded-radius-sm border border-border bg-surface px-2 py-1.5 text-xs text-text focus:outline-none focus:border-primary"
        >
          <option value="" disabled>
            排序
          </option>
          {SORT_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        {params.sort_by && (
          <button
            type="button"
            onClick={toggleSortOrder}
            title={sortOrder === 'asc' ? '升序' : '降序'}
            aria-label={`切换排序方向，当前${sortOrder === 'asc' ? '升序' : '降序'}`}
            className="w-7 h-7 flex items-center justify-center text-text-muted hover:text-text border border-border rounded-radius-sm bg-surface"
          >
            {sortOrder === 'asc' ? (
              <SortAsc className="w-3.5 h-3.5" />
            ) : (
              <SortDesc className="w-3.5 h-3.5" />
            )}
          </button>
        )}
      </div>

      {/* Clear filters */}
      {hasFilters && (
        <button
          type="button"
          onClick={clearFilters}
          title="清除过滤"
          aria-label="清除所有过滤条件"
          className="flex items-center gap-1 px-2 py-1.5 text-xs text-text-muted hover:text-text border border-border rounded-radius-sm bg-surface"
        >
          <Filter className="w-3 h-3" />
          清除
        </button>
      )}
    </div>
  );
}
