/**
 * TodoCreateForm — Enhanced creation form for TodoPage.
 *
 * Notion-style: title always visible, extra fields (description, priority,
 * due_at, project_tag) collapsed behind a "更多选项" toggle. Submit creates
 * via store.create() and resets the form.
 *
 * 字段块复用 ``TodoFields`` —— 与行内详情面板同一套控件，「建的时候能填的
 * 字段，事后也必须能改」不会各自漂移。
 */
import { ChevronDown, ChevronUp, Plus } from 'lucide-react';
import { useState } from 'react';

import type { CreateTodoInput } from '../../shared/api/types';

import { EMPTY_TODO_FIELDS, TodoFields, parseTagsText } from './TodoFields';
import type { TodoFieldsValue } from './TodoFields';
import { toIsoString } from './todoDateUtils';

interface TodoCreateFormProps {
  onCreate: (input: CreateTodoInput) => Promise<void>;
  busy: boolean;
  /** 阶段 3：可选专家列表（专家专属待办）；空/未提供时不显示选择器。 */
  specialists?: Array<{ id: string; name: string }>;
}

export function TodoCreateForm({ onCreate, busy, specialists = [] }: TodoCreateFormProps) {
  const [expanded, setExpanded] = useState(false);
  const [title, setTitle] = useState('');
  const [fields, setFields] = useState<TodoFieldsValue>(EMPTY_TODO_FIELDS);

  const canSubmit = title.trim().length > 0 && !busy;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;

    const input: CreateTodoInput = { title: title.trim() };
    if (fields.description.trim()) input.description = fields.description.trim();
    if (fields.priority !== 'medium') input.priority = fields.priority;
    if (fields.dueAtLocal) input.due_at = toIsoString(fields.dueAtLocal);
    if (fields.projectTag.trim()) input.project_tag = fields.projectTag.trim();
    // 标签以逗号/空白分隔，清洗口径与后端 todo_tags 一致。
    const tags = parseTagsText(fields.tagsText);
    if (tags.length > 0) input.tags = tags;
    if (fields.reminderOffsets.length > 0) input.reminder_offsets = fields.reminderOffsets;
    if (fields.specialistId) input.specialist_id = fields.specialistId;

    await onCreate(input);

    // Reset form
    setTitle('');
    setFields(EMPTY_TODO_FIELDS);
  };

  return (
    <form
      onSubmit={(e) => {
        void handleSubmit(e);
      }}
      className="mb-3 border border-border rounded-radius-sm bg-surface overflow-hidden"
      aria-label="新建待办"
    >
      {/* Title row — always visible */}
      <div className="flex items-center gap-2 px-3 py-2">
        <Plus className="w-4 h-4 text-text-muted flex-shrink-0" />
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onFocus={() => {
            if (!expanded) setExpanded(true);
          }}
          placeholder="输入待办标题..."
          aria-label="待办标题"
          className="flex-1 text-sm bg-transparent focus:outline-none placeholder:text-text-muted"
          data-testid="todo-create-title"
        />
        <button
          type="submit"
          disabled={!canSubmit}
          data-testid="todo-submit"
          className="flex items-center gap-1 px-2.5 py-1 bg-primary text-text-inverse text-xs rounded-radius-sm hover:bg-primary-hover disabled:opacity-40 disabled:cursor-not-allowed flex-shrink-0"
        >
          添加
        </button>
      </div>

      {/* Expand toggle */}
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1 w-full px-3 py-1 text-ui-xs text-text-muted hover:text-text hover:bg-bg-hover/50 border-t border-border/50"
        aria-expanded={expanded}
        aria-label={expanded ? '收起详细选项' : '展开详细选项'}
      >
        {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
        更多选项
      </button>

      {/* Expanded fields — 与行内详情面板共用 TodoFields */}
      {expanded && (
        <div className="px-3 pb-3 pt-2 border-t border-border/50">
          <TodoFields
            value={fields}
            onChange={setFields}
            specialists={specialists}
            testIdPrefix=""
          />
        </div>
      )}
    </form>
  );
}
