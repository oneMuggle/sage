/**
 * TodoDetailPanel — 行内展开的待办详情面板（P0：事后可编辑）。
 *
 * 挂在待办行下方而不是弹模态框：展开后原行仍可见，改一个字段不会把列表
 * 上下文丢掉。
 *
 * 落库时机按字段分两档：
 * - 立即提交：优先级 / 提醒档位 / 负责人 —— 「点一下就定」的开关；
 * - 失焦提交：描述 / 截止日期 / 项目标签 / 标签 —— 打字过程中不该写库。
 *   描述另有 Ctrl/Cmd+Enter 快捷提交；收起面板时兜底提交一次没失焦的字段。
 *
 * 清空语义：后端 PUT 是三态语义（缺省 = 不动、显式 null = 清空）。IPC 的
 * ``JSON.stringify`` 会丢掉 ``undefined``，所以清空一律发 ``null``，
 * 绝不发 ``undefined``（发 ``undefined`` 等于「不动」，清空会静默失效）。
 *
 * 「已落库值」单独记一份（``persistedRef``）：同一次展开里，父组件往往还
 * 没把新值回传，若拿 ``todo`` prop 当基准，收起面板时的兜底提交会把已经
 * 写过的字段再写一遍。
 */
import { AlertCircle, ChevronUp } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';

import type { Todo, UpdateTodoInput } from '../../shared/api/types';

import { TodoFields } from './TodoFields';
import type { TodoFieldsField, TodoFieldsValue } from './TodoFields';
import { parseTagsText } from './TodoFields';
import { toIsoString, toLocalDatetimeValue } from './todoDateUtils';

interface TodoDetailPanelProps {
  todo: Todo;
  /** 阶段 3：可选专家列表；空/未提供时不显示负责人选择器。 */
  specialists?: Array<{ id: string; name: string }>;
  onUpdate: (id: number, changes: UpdateTodoInput) => Promise<void>;
  onClose: () => void;
}

/** 待办行 → 字段草稿。 */
export function todoToFieldsValue(todo: Todo): TodoFieldsValue {
  return {
    description: todo.description ?? '',
    priority: todo.priority,
    dueAtLocal: todo.due_at ? toLocalDatetimeValue(todo.due_at) : '',
    projectTag: todo.project_tag ?? '',
    tagsText: (todo.tags ?? []).join(', '),
    reminderOffsets: todo.reminder_offsets ?? [],
    specialistId: todo.specialist_id ?? '',
  };
}

function sameTags(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((tag, i) => tag === b[i]);
}

function sameNumbers(a: number[], b: number[]): boolean {
  return a.length === b.length && a.every((v, i) => v === b[i]);
}

export function TodoDetailPanel({
  todo,
  specialists = [],
  onUpdate,
  onClose,
}: TodoDetailPanelProps) {
  const [draft, setDraft] = useState<TodoFieldsValue>(() => todoToFieldsValue(todo));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 并发写库计数：先发的请求回来时不能把还在飞的那个的「保存中」抹掉。
  const pendingRef = useRef(0);
  // 已落库的字段值。比较基准用它，而不是 todo prop —— 同一次展开里父组件
  // 往往还没回传新值，用 prop 当基准会把写过的字段再写一遍。
  const persistedRef = useRef<TodoFieldsValue>(todoToFieldsValue(todo));

  // 换一条待办时重置草稿。同一条待办的字段回包不重置 —— 否则用户正在打的
  // 字会被后端回来的旧值冲掉。
  useEffect(() => {
    const fresh = todoToFieldsValue(todo);
    setDraft(fresh);
    persistedRef.current = fresh;
    setError(null);
  }, [todo.id]);

  const persist = useCallback(
    async (
      changes: UpdateTodoInput,
      revert: Partial<TodoFieldsValue>,
      applied: Partial<TodoFieldsValue>,
    ) => {
      pendingRef.current += 1;
      setSaving(true);
      setError(null);
      try {
        await onUpdate(todo.id, changes);
        persistedRef.current = { ...persistedRef.current, ...applied };
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : String(e));
        // 只回滚这一个字段：其余用户正在填的内容不该被一次失败抹掉。
        setDraft((prev) => ({ ...prev, ...revert }));
      } finally {
        pendingRef.current -= 1;
        if (pendingRef.current <= 0) setSaving(false);
      }
    },
    [onUpdate, todo.id],
  );

  // ---------- 失焦提交 ----------

  const commitDescription = () => {
    const value = draft.description.trim();
    if (value === persistedRef.current.description.trim()) return;
    void persist(
      { description: value || null },
      { description: persistedRef.current.description },
      { description: value },
    );
  };

  const commitDueAt = () => {
    if (draft.dueAtLocal === persistedRef.current.dueAtLocal) return;
    const iso = draft.dueAtLocal ? toIsoString(draft.dueAtLocal) : '';
    void persist(
      { due_at: iso || null },
      { dueAtLocal: persistedRef.current.dueAtLocal },
      { dueAtLocal: draft.dueAtLocal },
    );
  };

  const commitProjectTag = () => {
    const value = draft.projectTag.trim();
    if (value === persistedRef.current.projectTag.trim()) return;
    void persist(
      { project_tag: value || null },
      { projectTag: persistedRef.current.projectTag },
      { projectTag: value },
    );
  };

  const commitTags = () => {
    const next = parseTagsText(draft.tagsText);
    const current = parseTagsText(persistedRef.current.tagsText);
    if (sameTags(next, current)) return;
    void persist(
      { tags: next },
      { tagsText: persistedRef.current.tagsText },
      { tagsText: draft.tagsText },
    );
  };

  /** 收起前兜底提交：把还没失焦的字段一并落库。 */
  const flush = () => {
    commitDescription();
    commitDueAt();
    commitProjectTag();
    commitTags();
  };

  const handleFieldCommit = (field: TodoFieldsField) => {
    if (field === 'description') commitDescription();
    else if (field === 'dueAtLocal') commitDueAt();
    else if (field === 'projectTag') commitProjectTag();
    else if (field === 'tagsText') commitTags();
  };

  // ---------- 立即提交 ----------

  const handleChange = (next: TodoFieldsValue) => {
    setDraft(next);
    if (next.priority !== draft.priority) {
      void persist(
        { priority: next.priority },
        { priority: persistedRef.current.priority },
        { priority: next.priority },
      );
    }
    if (!sameNumbers(next.reminderOffsets, draft.reminderOffsets)) {
      void persist(
        { reminder_offsets: next.reminderOffsets },
        { reminderOffsets: persistedRef.current.reminderOffsets },
        { reminderOffsets: next.reminderOffsets },
      );
    }
    if (next.specialistId !== draft.specialistId) {
      void persist(
        { specialist_id: next.specialistId || null },
        { specialistId: persistedRef.current.specialistId },
        { specialistId: next.specialistId },
      );
    }
  };

  const handleClose = () => {
    flush();
    onClose();
  };

  return (
    <div
      className="mt-1.5 ml-7 mr-1 p-2.5 rounded-radius-sm border border-border bg-bg-muted/20"
      data-testid={`todo-detail-panel-${todo.id}`}
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          e.stopPropagation();
          handleClose();
        }
      }}
    >
      <div className="mb-2 flex items-center justify-between">
        <span className="text-ui-xs text-text-muted">待办详情</span>
        <div className="flex items-center gap-2">
          {saving && <span className="text-ui-xs text-text-muted">保存中…</span>}
          {error && (
            <span
              className="flex items-center gap-1 text-ui-xs text-red-600"
              role="alert"
              data-testid={`todo-detail-error-${todo.id}`}
            >
              <AlertCircle className="w-3 h-3" />
              {error}
            </span>
          )}
          <button
            type="button"
            onClick={handleClose}
            title="收起详情"
            aria-label="收起详情"
            data-testid={`todo-detail-close-${todo.id}`}
            className="w-6 h-6 flex items-center justify-center text-text-muted hover:text-text hover:bg-bg-hover rounded flex-shrink-0"
          >
            <ChevronUp className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      <TodoFields
        value={draft}
        onChange={handleChange}
        onFieldCommit={handleFieldCommit}
        specialists={specialists}
        testIdPrefix="detail-"
      />
    </div>
  );
}
