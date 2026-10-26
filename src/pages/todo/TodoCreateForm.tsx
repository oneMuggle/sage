/**
 * TodoCreateForm — Enhanced creation form for TodoPage.
 *
 * Notion-style: title always visible, extra fields (description, priority,
 * due_at, project_tag) collapsed behind a "更多选项" toggle. Submit creates
 * via store.create() and resets the form.
 */
import { Calendar, ChevronDown, ChevronUp, Flag, Plus, Tag } from 'lucide-react';
import { useState } from 'react';

import type { CreateTodoInput, TodoPriority } from '../../shared/api/types';

import { toIsoString } from './todoDateUtils';

interface TodoCreateFormProps {
  onCreate: (input: CreateTodoInput) => Promise<void>;
  busy: boolean;
}

const PRIORITY_CONFIG: Array<{
  value: TodoPriority;
  label: string;
  color: string;
  icon: string;
}> = [
  { value: 'low', label: '低', color: 'text-green-600', icon: '🟢' },
  { value: 'medium', label: '中', color: 'text-yellow-600', icon: '🟡' },
  { value: 'high', label: '高', color: 'text-red-600', icon: '🔴' },
];

export function TodoCreateForm({ onCreate, busy }: TodoCreateFormProps) {
  const [expanded, setExpanded] = useState(false);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [priority, setPriority] = useState<TodoPriority>('medium');
  const [dueAtLocal, setDueAtLocal] = useState('');
  const [projectTag, setProjectTag] = useState('');

  const canSubmit = title.trim().length > 0 && !busy;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;

    const input: CreateTodoInput = { title: title.trim() };
    if (description.trim()) input.description = description.trim();
    if (priority !== 'medium') input.priority = priority;
    if (dueAtLocal) input.due_at = toIsoString(dueAtLocal);
    if (projectTag.trim()) input.project_tag = projectTag.trim();

    await onCreate(input);

    // Reset form
    setTitle('');
    setDescription('');
    setPriority('medium');
    setDueAtLocal('');
    setProjectTag('');
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

      {/* Expanded fields */}
      {expanded && (
        <div className="px-3 pb-3 pt-1 space-y-2.5 border-t border-border/50">
          {/* Description */}
          <div>
            <label className="block text-ui-xs text-text-muted mb-1">描述</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="添加详细描述..."
              rows={2}
              className="w-full px-2.5 py-1.5 text-xs border border-border rounded-radius-sm bg-background focus:outline-none focus:border-primary resize-none placeholder:text-text-muted"
            />
          </div>

          {/* Priority */}
          <div>
            <label className="flex items-center gap-1 text-ui-xs text-text-muted mb-1">
              <Flag className="w-3 h-3" />
              优先级
            </label>
            <div className="flex gap-1.5">
              {PRIORITY_CONFIG.map((p) => (
                <button
                  key={p.value}
                  type="button"
                  onClick={() => setPriority(p.value)}
                  className={`flex items-center gap-1 px-2 py-1 text-xs rounded-radius-sm border transition-colors ${
                    priority === p.value
                      ? `border-primary bg-primary/10 ${p.color}`
                      : 'border-border text-text-muted hover:border-primary/50'
                  }`}
                  aria-pressed={priority === p.value}
                >
                  <span>{p.icon}</span>
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          <div className="flex gap-3">
            {/* Due date */}
            <div className="flex-1">
              <label className="flex items-center gap-1 text-ui-xs text-text-muted mb-1">
                <Calendar className="w-3 h-3" />
                截止日期
              </label>
              <input
                type="datetime-local"
                value={dueAtLocal}
                onChange={(e) => setDueAtLocal(e.target.value)}
                className="w-full px-2 py-1.5 text-xs border border-border rounded-radius-sm bg-background focus:outline-none focus:border-primary"
              />
            </div>

            {/* Project tag */}
            <div className="flex-1">
              <label className="flex items-center gap-1 text-ui-xs text-text-muted mb-1">
                <Tag className="w-3 h-3" />
                项目标签
              </label>
              <input
                type="text"
                value={projectTag}
                onChange={(e) => setProjectTag(e.target.value)}
                placeholder="关联项目..."
                className="w-full px-2.5 py-1.5 text-xs border border-border rounded-radius-sm bg-background focus:outline-none focus:border-primary placeholder:text-text-muted"
              />
            </div>
          </div>
        </div>
      )}
    </form>
  );
}
