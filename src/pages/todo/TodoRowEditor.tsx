/**
 * TodoRowEditor — A single todo row with inline editing.
 *
 * Notion-style interactions:
 * - Click title → inline input, Enter/blur saves, Escape cancels
 * - Click priority badge → cycle through high/medium/low
 * - Click due date → date picker popup
 * - Checkbox on left for batch selection
 * - Status indicators: complete button, ✓ completed, ✗ cancelled
 */
import { Calendar, Check, X } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';

import type { Todo, TodoPriority, UpdateTodoInput } from '../../shared/api/types';
import { TwoStepDelete } from '../../widgets/sidebar/TwoStepDelete';

import { toLocalDatetimeValue, toIsoString } from './todoDateUtils';

interface TodoRowEditorProps {
  todo: Todo;
  selected: boolean;
  onSelect: (id: number, selected: boolean) => void;
  onUpdate: (id: number, changes: UpdateTodoInput) => Promise<void>;
  onComplete: (id: number) => Promise<void>;
  onCancel: (id: number) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
}

const PRIORITY_CYCLE: TodoPriority[] = ['low', 'medium', 'high'];

const PRIORITY_DISPLAY: Record<TodoPriority, { label: string; color: string; bg: string }> = {
  high: { label: '高', color: 'text-red-600', bg: 'bg-red-50 dark:bg-red-900/20' },
  medium: {
    label: '中',
    color: 'text-yellow-600',
    bg: 'bg-yellow-50 dark:bg-yellow-900/20',
  },
  low: {
    label: '低',
    color: 'text-green-600',
    bg: 'bg-green-50 dark:bg-green-900/20',
  },
};

function formatDueDate(isoStr: string): string {
  try {
    const d = new Date(isoStr);
    const now = new Date();
    const isOverdue = d < now;
    const isToday = d.toDateString() === now.toDateString();
    const isTomorrow = d.toDateString() === new Date(now.getTime() + 86400000).toDateString();

    const timeStr = d.toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
    });

    if (isOverdue) return `逾期 ${timeStr}`;
    if (isToday) return `今天 ${timeStr}`;
    if (isTomorrow) return `明天 ${timeStr}`;
    return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' });
  } catch {
    return '';
  }
}

export function TodoRowEditor({
  todo,
  selected,
  onSelect,
  onUpdate,
  onComplete,
  onCancel,
  onDelete,
}: TodoRowEditorProps) {
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState(todo.title);
  const [showDatePicker, setShowDatePicker] = useState(false);
  const titleInputRef = useRef<HTMLInputElement>(null);
  const datePickerRef = useRef<HTMLDivElement>(null);

  const isDone = todo.status === 'completed';
  const isCancelled = todo.status === 'cancelled';
  const isInactive = isDone || isCancelled;

  useEffect(() => {
    if (editingTitle && titleInputRef.current) {
      titleInputRef.current.focus();
      titleInputRef.current.select();
    }
  }, [editingTitle]);

  useEffect(() => {
    if (!showDatePicker) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (datePickerRef.current && !datePickerRef.current.contains(e.target as Node)) {
        setShowDatePicker(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showDatePicker]);

  const commitTitle = useCallback(() => {
    const trimmed = titleDraft.trim();
    if (trimmed && trimmed !== todo.title) {
      void onUpdate(todo.id, { title: trimmed });
    } else {
      setTitleDraft(todo.title);
    }
    setEditingTitle(false);
  }, [titleDraft, todo.id, todo.title, onUpdate]);

  const handleTitleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      commitTitle();
    } else if (e.key === 'Escape') {
      setTitleDraft(todo.title);
      setEditingTitle(false);
    }
  };

  const cyclePriority = () => {
    if (isInactive) return;
    const currentIdx = PRIORITY_CYCLE.indexOf(todo.priority);
    const nextPriority = PRIORITY_CYCLE[(currentIdx + 1) % PRIORITY_CYCLE.length];
    void onUpdate(todo.id, { priority: nextPriority });
  };

  const handleDueDateChange = (localValue: string) => {
    const iso = localValue ? toIsoString(localValue) : '';
    void onUpdate(todo.id, { due_at: iso || undefined });
    setShowDatePicker(false);
  };

  const clearDueDate = () => {
    void onUpdate(todo.id, { due_at: undefined });
    setShowDatePicker(false);
  };

  const priorityConf = PRIORITY_DISPLAY[todo.priority];

  return (
    <li
      className={`flex items-center gap-2 px-3 py-2 border border-border rounded-radius-sm group transition-colors ${
        isInactive ? 'bg-bg-muted/20' : 'bg-surface hover:bg-bg-hover/30'
      } ${selected ? 'ring-1 ring-primary/30' : ''}`}
    >
      {/* Checkbox */}
      <input
        type="checkbox"
        checked={selected}
        onChange={(e) => onSelect(todo.id, e.target.checked)}
        className="w-3.5 h-3.5 rounded border-border accent-primary cursor-pointer flex-shrink-0"
        aria-label={`选择 ${todo.title}`}
      />

      {/* Status toggle */}
      {!isInactive && (
        <button
          type="button"
          onClick={() => void onComplete(todo.id)}
          title="标记完成"
          aria-label={`完成 ${todo.title}`}
          className="w-5 h-5 flex items-center justify-center rounded-full border border-border hover:border-green-500 hover:bg-green-50 dark:hover:bg-green-900/20 text-text-muted hover:text-green-600 flex-shrink-0"
        >
          <Check className="w-3 h-3 opacity-0 group-hover:opacity-100" />
        </button>
      )}
      {isDone && (
        <span className="w-5 h-5 flex items-center justify-center rounded-full bg-green-100 dark:bg-green-900/30 text-green-600 flex-shrink-0">
          <Check className="w-3 h-3" />
        </span>
      )}
      {isCancelled && (
        <span className="w-5 h-5 flex items-center justify-center rounded-full bg-bg-muted text-text-muted flex-shrink-0">
          <X className="w-3 h-3" />
        </span>
      )}

      {/* Title (inline editable) */}
      <div className="flex-1 min-w-0">
        {editingTitle ? (
          <input
            ref={titleInputRef}
            type="text"
            value={titleDraft}
            onChange={(e) => setTitleDraft(e.target.value)}
            onBlur={commitTitle}
            onKeyDown={handleTitleKeyDown}
            className="w-full text-sm px-1 py-0.5 border border-primary rounded bg-background focus:outline-none"
            data-testid="todo-title-edit-input"
          />
        ) : (
          <button
            type="button"
            onClick={() => {
              if (!isInactive) {
                setTitleDraft(todo.title);
                setEditingTitle(true);
              }
            }}
            className={`text-sm text-left truncate w-full ${
              isInactive ? 'line-through text-text-muted' : 'text-text'
            } hover:text-primary cursor-text`}
            title="点击编辑标题"
          >
            {todo.title}
          </button>
        )}
      </div>

      {/* Description indicator */}
      {todo.description && !editingTitle && (
        <span className="text-ui-xs text-text-muted px-1" title={todo.description}>
          📝
        </span>
      )}

      {/* Priority badge (clickable to cycle) */}
      <button
        type="button"
        onClick={cyclePriority}
        title={`优先级：${priorityConf.label}（点击切换）`}
        aria-label={`优先级 ${priorityConf.label}，点击切换`}
        className={`flex items-center gap-0.5 px-1.5 py-0.5 text-ui-xs rounded-full ${priorityConf.bg} ${priorityConf.color} hover:opacity-80 flex-shrink-0`}
      >
        {priorityConf.label}
      </button>

      {/* Due date (clickable to edit) */}
      {todo.due_at && (
        <div className="relative flex-shrink-0" ref={datePickerRef}>
          <button
            type="button"
            onClick={() => setShowDatePicker(!showDatePicker)}
            title="修改截止日期"
            className={`flex items-center gap-1 px-1.5 py-0.5 text-ui-xs rounded-full border ${
              new Date(todo.due_at) < new Date() && !isInactive
                ? 'border-red-300 bg-red-50 dark:bg-red-900/20 text-red-600'
                : 'border-border text-text-muted hover:border-primary'
            }`}
          >
            <Calendar className="w-3 h-3" />
            {formatDueDate(todo.due_at)}
          </button>

          {showDatePicker && (
            <div className="absolute right-0 top-full mt-1 z-50 p-2 bg-surface border border-border rounded-radius-sm shadow-lg">
              <input
                type="datetime-local"
                value={toLocalDatetimeValue(todo.due_at)}
                onChange={(e) => handleDueDateChange(e.target.value)}
                className="px-2 py-1 text-xs border border-border rounded bg-background focus:outline-none focus:border-primary"
                autoFocus
              />
              <button
                type="button"
                onClick={clearDueDate}
                className="mt-1 w-full text-ui-xs text-text-muted hover:text-red-600 py-0.5"
              >
                清除日期
              </button>
            </div>
          )}
        </div>
      )}

      {/* Project tag */}
      {todo.project_tag && (
        <span className="flex items-center gap-0.5 px-1.5 py-0.5 text-ui-xs rounded-full bg-blue-50 dark:bg-blue-900/20 text-blue-600 flex-shrink-0">
          {todo.project_tag}
        </span>
      )}

      {/* Cancel button (for active items) */}
      {!isDone && !isCancelled && (
        <button
          type="button"
          onClick={() => void onCancel(todo.id)}
          title="取消待办"
          aria-label={`取消 ${todo.title}`}
          className="w-6 h-6 flex items-center justify-center text-text-muted hover:text-orange-600 hover:bg-bg-hover rounded opacity-0 group-hover:opacity-100 flex-shrink-0"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      )}

      {/* Delete (two-step) */}
      <TwoStepDelete
        onConfirm={() => void onDelete(todo.id)}
        label={`删除 ${todo.title}`}
        armedLabel="确认删除?"
        data-testid={`todo-delete-${todo.id}`}
        className="w-6 h-6 justify-center opacity-0 group-hover:opacity-100 flex-shrink-0"
      />
    </li>
  );
}
