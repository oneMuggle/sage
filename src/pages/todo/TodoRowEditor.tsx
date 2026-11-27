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
import {
  Bell,
  Calendar,
  Check,
  CheckCircle2,
  CircleDot,
  Clock3,
  Copy,
  Flag,
  Pencil,
  Play,
  Plus,
  Settings2,
  Trash2,
  X,
  XCircle,
} from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';

import type { Todo, TodoItemStatus, TodoPriority, UpdateTodoInput } from '../../shared/api/types';
import { copyToClipboard } from '../../shared/lib/clipboard';
import { fillTemplate } from '../../shared/lib/formatTemplate';
import { useI18n } from '../../shared/lib/i18n';
import { confirmDialog } from '../../shared/ui/ConfirmDialog/confirmService';
import { ContextMenu } from '../../shared/ui/ContextMenu/ContextMenu';
import type { ContextMenuItemSpec } from '../../shared/ui/ContextMenu/types';
import { TwoStepDelete } from '../../widgets/sidebar/TwoStepDelete';

import { TodoDetailPanel } from './TodoDetailPanel';
import { toLocalDatetimeValue, toIsoString } from './todoDateUtils';

interface TodoRowEditorProps {
  todo: Todo;
  selected: boolean;
  onSelect: (id: number, selected: boolean) => void;
  onUpdate: (id: number, changes: UpdateTodoInput) => Promise<void>;
  onComplete: (id: number) => Promise<void>;
  onCancel: (id: number) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
  /** 仅顶层行提供：行内创建子任务（最多两级）。 */
  onAddSubtask?: (parentId: number, title: string) => Promise<void>;
  /** 阶段 3：稍后提醒（due_at 后移 N 分钟）。 */
  onSnooze?: (id: number, minutes: number) => Promise<void>;
  /** 详情面板的负责人候选项（专家列表）。 */
  specialists?: Array<{ id: string; name: string }>;
}

const PRIORITY_CYCLE: TodoPriority[] = ['low', 'medium', 'high'];

/**
 * 三态循环：未开始 → 进行中 → 已完成 → 未开始。
 *
 * 与后端 ``todo_status.next_cycle_status`` 同口径；``cancelled`` 不在循环内
 * （取消只能显式触发，右上角的 ✕ 按钮负责）。
 */
const STATUS_CYCLE: Partial<Record<TodoItemStatus, TodoItemStatus>> = {
  pending: 'in_progress',
  in_progress: 'completed',
  completed: 'pending',
};

/** 三态按钮的悬浮提示 —— 说明「点一下会变成什么」。 */
const STATUS_CYCLE_HINT: Record<'pending' | 'in_progress' | 'completed', string> = {
  pending: '未开始（点击标记为进行中）',
  in_progress: '进行中（点击标记为已完成）',
  completed: '已完成（点击重新打开为未开始）',
};

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
  onAddSubtask,
  onSnooze,
  specialists = [],
}: TodoRowEditorProps) {
  const { t } = useI18n();
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState(todo.title);
  const [showDatePicker, setShowDatePicker] = useState(false);
  const [addingSubtask, setAddingSubtask] = useState(false);
  const [subtaskDraft, setSubtaskDraft] = useState('');
  const [showDetail, setShowDetail] = useState(false);
  const titleInputRef = useRef<HTMLInputElement>(null);
  const subtaskInputRef = useRef<HTMLInputElement>(null);
  const datePickerRef = useRef<HTMLDivElement>(null);
  // Enter 提交后、await 完成前若触发 blur，防止重复创建同一子任务。
  const committingSubtask = useRef(false);

  const isDone = todo.status === 'completed';
  const isCancelled = todo.status === 'cancelled';
  const isInactive = isDone || isCancelled;
  const isInProgress = todo.status === 'in_progress';

  useEffect(() => {
    if (editingTitle && titleInputRef.current) {
      titleInputRef.current.focus();
      titleInputRef.current.select();
    }
  }, [editingTitle]);

  useEffect(() => {
    if (addingSubtask) subtaskInputRef.current?.focus();
  }, [addingSubtask]);

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

  /**
   * 三态循环：未开始 → 进行中 → 已完成 → 未开始。
   *
   * 走 PUT /todos/{id} 的 status 字段而不是单独的 complete 接口：后端在
   * status='completed' 时分派到 complete_todo，完成打戳与重复任务的下一次
   * 派生都照旧发生；已完成再点一次回到未开始时后端会清掉完成时间戳。
   */
  const cycleStatus = () => {
    const next = STATUS_CYCLE[todo.status];
    if (!next) return;
    void onUpdate(todo.id, { status: next });
  };

  const handleDueDateChange = (localValue: string) => {
    const iso = localValue ? toIsoString(localValue) : '';
    // 清空必须发 null：IPC 的 JSON 序列化会丢掉 undefined，
    // 发 undefined 等于「不动」，清空会静默失效。
    void onUpdate(todo.id, { due_at: iso || null });
    setShowDatePicker(false);
  };

  const clearDueDate = () => {
    void onUpdate(todo.id, { due_at: null });
    setShowDatePicker(false);
  };

  const commitSubtask = useCallback(async () => {
    if (committingSubtask.current) return;
    const trimmed = subtaskDraft.trim();
    if (!trimmed || !onAddSubtask) {
      setAddingSubtask(false);
      setSubtaskDraft('');
      return;
    }
    committingSubtask.current = true;
    try {
      await onAddSubtask(todo.id, trimmed);
      setSubtaskDraft('');
      setAddingSubtask(false);
    } finally {
      committingSubtask.current = false;
    }
  }, [subtaskDraft, onAddSubtask, todo.id]);

  const handleSubtaskKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      void commitSubtask();
    } else if (e.key === 'Escape') {
      setSubtaskDraft('');
      setAddingSubtask(false);
    }
  };

  const priorityConf = PRIORITY_DISPLAY[todo.priority];

  const menuItems = (): ContextMenuItemSpec[] => {
    const items: ContextMenuItemSpec[] = [];
    if (!isInactive) {
      items.push(
        {
          id: 'todo-edit-title',
          label: t('contextMenu.todo.editTitle'),
          icon: Pencil,
          onSelect: () => {
            setTitleDraft(todo.title);
            setEditingTitle(true);
          },
        },
        {
          id: 'todo-complete',
          label: t('contextMenu.todo.complete'),
          icon: CheckCircle2,
          onSelect: () => void onComplete(todo.id),
        },
        {
          id: 'todo-cancel',
          label: t('contextMenu.todo.cancel'),
          icon: XCircle,
          onSelect: () => void onCancel(todo.id),
        },
        {
          id: 'todo-priority',
          label: t('contextMenu.todo.priority'),
          icon: Flag,
          submenu: [
            {
              id: 'todo-priority-high',
              label: t('contextMenu.todo.priorityHigh'),
              onSelect: () => void onUpdate(todo.id, { priority: 'high' }),
            },
            {
              id: 'todo-priority-medium',
              label: t('contextMenu.todo.priorityMedium'),
              onSelect: () => void onUpdate(todo.id, { priority: 'medium' }),
            },
            {
              id: 'todo-priority-low',
              label: t('contextMenu.todo.priorityLow'),
              onSelect: () => void onUpdate(todo.id, { priority: 'low' }),
            },
          ],
        },
      );
      if (onSnooze) {
        items.push({
          id: 'todo-snooze',
          label: '稍后提醒',
          icon: Clock3,
          submenu: [
            {
              id: 'todo-snooze-10',
              label: '10 分钟后',
              onSelect: () => void onSnooze(todo.id, 10),
            },
            {
              id: 'todo-snooze-60',
              label: '1 小时后',
              onSelect: () => void onSnooze(todo.id, 60),
            },
            {
              id: 'todo-snooze-1440',
              label: '明天',
              onSelect: () => void onSnooze(todo.id, 24 * 60),
            },
          ],
        });
      }
    }
    items.push(
      {
        id: 'todo-copy-title',
        label: t('contextMenu.todo.copyTitle'),
        icon: Copy,
        onSelect: () =>
          void copyToClipboard(todo.title, {
            successMessage: t('contextMenu.common.copied'),
            errorMessage: t('contextMenu.common.copyFailed'),
          }),
      },
      { id: 'todo-sep-delete', kind: 'separator' },
      {
        id: 'todo-delete',
        label: t('contextMenu.todo.delete'),
        icon: Trash2,
        destructive: true,
        onSelect: async () => {
          const confirmed = await confirmDialog({
            title: t('contextMenu.todo.deleteTitle'),
            message: fillTemplate(t('contextMenu.todo.deleteBody'), { title: todo.title }),
            confirmLabel: t('common.delete'),
            danger: true,
          });
          if (confirmed) await onDelete(todo.id);
        },
      },
    );
    return items;
  };

  return (
    <ContextMenu items={menuItems} enabled={!editingTitle && !showDatePicker}>
      <li
        className={`relative flex flex-col px-3 py-2 border border-border rounded-radius-sm group transition-colors ${
          isInactive ? 'bg-bg-muted/20' : 'bg-surface hover:bg-bg-hover/30'
        } ${selected ? 'ring-1 ring-primary/30' : ''}`}
      >
        {/* 进行中的视觉标识：左侧主色竖条 */}
        {isInProgress && (
          <span
            className="absolute left-0 top-0 bottom-0 w-0.5 bg-primary rounded-l-radius-sm"
            aria-hidden="true"
            data-testid={`todo-in-progress-bar-${todo.id}`}
          />
        )}
        <div className="flex items-center gap-2">
          {/* Checkbox */}
          <input
            type="checkbox"
            checked={selected}
            onChange={(e) => onSelect(todo.id, e.target.checked)}
            className="w-3.5 h-3.5 rounded border-border accent-primary cursor-pointer flex-shrink-0"
            aria-label={`选择 ${todo.title}`}
          />

          {/* 状态按钮：三态循环（未开始 → 进行中 → 已完成 → 未开始） */}
          {!isCancelled ? (
            <button
              type="button"
              onClick={() => void cycleStatus()}
              title={STATUS_CYCLE_HINT[todo.status as 'pending' | 'in_progress' | 'completed']}
              aria-label={`${STATUS_CYCLE_HINT[todo.status as 'pending' | 'in_progress' | 'completed']} ${todo.title}`}
              data-testid={`todo-status-${todo.id}`}
              className={`w-5 h-5 flex items-center justify-center rounded-full flex-shrink-0 transition-colors ${
                todo.status === 'completed'
                  ? 'bg-green-100 dark:bg-green-900/30 text-green-600'
                  : todo.status === 'in_progress'
                    ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-600'
                    : 'border border-border text-text-muted hover:border-primary hover:text-primary'
              }`}
            >
              {todo.status === 'completed' ? (
                <Check className="w-3 h-3" />
              ) : todo.status === 'in_progress' ? (
                <CircleDot className="w-3 h-3" />
              ) : (
                <Play className="w-2.5 h-2.5 opacity-0 group-hover:opacity-100" />
              )}
            </button>
          ) : (
            <span
              className="w-5 h-5 flex items-center justify-center rounded-full bg-bg-muted text-text-muted flex-shrink-0"
              title="已取消"
              data-testid={`todo-status-${todo.id}`}
            >
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

          {/* 详情开关（行内可编辑：描述 / 截止日期 / 项目 / 标签 / 提醒 / 负责人） */}
          {!editingTitle && (
            <button
              type="button"
              onClick={() => setShowDetail((prev) => !prev)}
              title="编辑待办详情"
              aria-label={`编辑 ${todo.title} 的详情`}
              aria-expanded={showDetail}
              data-testid={`todo-detail-toggle-${todo.id}`}
              className={`w-6 h-6 flex items-center justify-center rounded flex-shrink-0 transition-colors ${
                showDetail
                  ? 'text-primary bg-primary/10'
                  : 'text-text-muted hover:text-primary hover:bg-bg-hover'
              }`}
            >
              <Settings2 className="w-3.5 h-3.5" />
            </button>
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

          {/* Tags（最多 3 个 + 溢出计数） */}
          {(todo.tags ?? []).slice(0, 3).map((tag) => (
            <span
              key={tag}
              className="px-1.5 py-0.5 text-ui-xs rounded-full bg-bg-muted text-text-muted flex-shrink-0"
              title={`标签：${tag}`}
            >
              #{tag}
            </span>
          ))}
          {(todo.tags?.length ?? 0) > 3 && (
            <span
              className="text-ui-xs text-text-muted flex-shrink-0"
              title={(todo.tags ?? []).join(', ')}
            >
              +{(todo.tags?.length ?? 0) - 3}
            </span>
          )}

          {/* 来源（阶段 2：对话提炼反向链接） */}
          {todo.source_type === 'chat' && (
            <span
              className="px-1.5 py-0.5 text-ui-xs rounded-full bg-primary/10 text-primary flex-shrink-0"
              title={`来自对话 ${todo.source_ref ?? ''}`}
              data-testid={`todo-source-${todo.id}`}
            >
              来自对话
            </span>
          )}

          {/* 专家归属（阶段 3） */}
          {todo.specialist_id && (
            <span
              className="px-1.5 py-0.5 text-ui-xs rounded-full bg-purple-50 dark:bg-purple-900/20 text-purple-600 flex-shrink-0"
              title={`专家专属：${todo.specialist_id}`}
              data-testid={`todo-specialist-${todo.id}`}
            >
              @{todo.specialist_id}
            </span>
          )}

          {/* 推迟次数（阶段 3；≥2 次提示容易拖延） */}
          {(todo.snooze_count ?? 0) >= 2 && (
            <span
              className="flex items-center gap-0.5 px-1.5 py-0.5 text-ui-xs rounded-full bg-amber-100 dark:bg-amber-900/30 text-amber-700 flex-shrink-0"
              title={`已推迟 ${todo.snooze_count} 次`}
              data-testid={`todo-snooze-badge-${todo.id}`}
            >
              <Clock3 className="w-3 h-3" />×{todo.snooze_count}
            </span>
          )}

          {/* 自定义提醒档位（有配置时显示） */}
          {(todo.reminder_offsets?.length ?? 0) > 0 && (
            <span
              className="flex items-center gap-0.5 px-1.5 py-0.5 text-ui-xs rounded-full bg-amber-50 dark:bg-amber-900/20 text-amber-600 flex-shrink-0"
              title={`提醒：${(todo.reminder_offsets ?? [])
                .map((m) =>
                  m >= 1440 ? `提前${m / 1440}天` : m >= 60 ? `提前${m / 60}小时` : `提前${m}分钟`,
                )
                .join('、')}`}
            >
              <Bell className="w-3 h-3" />
              {todo.reminder_offsets?.length}
            </span>
          )}

          {/* Add subtask (top-level rows only) */}
          {onAddSubtask && !isInactive && (
            <button
              type="button"
              onClick={() => setAddingSubtask(true)}
              title="添加子任务"
              aria-label={`为 ${todo.title} 添加子任务`}
              className="w-6 h-6 flex items-center justify-center text-text-muted hover:text-primary hover:bg-bg-hover rounded opacity-0 group-hover:opacity-100 flex-shrink-0"
            >
              <Plus className="w-3.5 h-3.5" />
            </button>
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
        </div>

        {/* Inline subtask creator */}
        {addingSubtask && onAddSubtask && (
          <div className="mt-1.5 pl-7 pr-1">
            <input
              ref={subtaskInputRef}
              type="text"
              value={subtaskDraft}
              onChange={(e) => setSubtaskDraft(e.target.value)}
              onBlur={() => void commitSubtask()}
              onKeyDown={handleSubtaskKeyDown}
              placeholder="子任务标题，回车创建，Esc 取消"
              data-testid="todo-subtask-input"
              className="w-full text-xs px-2 py-1 border border-primary rounded bg-background focus:outline-none"
            />
          </div>
        )}

        {/* 行内详情面板（可改描述 / 截止日期 / 项目 / 标签 / 提醒 / 负责人） */}
        {showDetail && (
          <TodoDetailPanel
            todo={todo}
            specialists={specialists}
            onUpdate={onUpdate}
            onClose={() => setShowDetail(false)}
          />
        )}
      </li>
    </ContextMenu>
  );
}
