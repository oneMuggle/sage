/**
 * TodoQuickAdd — 自然语言快速录入弹窗。
 *
 * 输入如「明天下午3点 交报告 !高 #工作」→ 本地 parseQuickTodo 实时解析
 * → 预览 chips（日期 / 优先级 / 标签）→ 回车或点按创建。
 */
import { Calendar, Flag, Hash } from 'lucide-react';
import { useMemo, useState } from 'react';

import type { CreateTodoInput, TodoPriority } from '../../shared/api/types';
import { Modal } from '../../shared/ui';

import { parseQuickTodo } from './parseQuickTodo';

interface TodoQuickAddProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (input: CreateTodoInput) => Promise<void>;
}

const PRIORITY_LABEL: Record<TodoPriority, string> = {
  high: '高',
  medium: '中',
  low: '低',
};

function formatDuePreview(dueAt: string): string {
  const d = new Date(dueAt);
  return d.toLocaleString('zh-CN', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function TodoQuickAdd({ isOpen, onClose, onSubmit }: TodoQuickAddProps) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const parsed = useMemo(() => parseQuickTodo(text), [text]);

  const canSubmit = parsed.title.trim().length > 0 && !busy;

  const handleClose = () => {
    setText('');
    onClose();
  };

  const handleSubmit = async () => {
    if (!canSubmit) return;
    const input: CreateTodoInput = { title: parsed.title };
    if (parsed.dueAt) input.due_at = parsed.dueAt;
    if (parsed.priority) input.priority = parsed.priority;
    if (parsed.tags.length > 0) input.tags = parsed.tags;

    setBusy(true);
    try {
      await onSubmit(input);
      setText('');
      onClose();
    } finally {
      setBusy(false);
    }
  };

  const hasPreview = Boolean(parsed.dueAt || parsed.priority || parsed.tags.length > 0);

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      title="快速添加待办"
      footer={
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={handleClose}
            className="px-3 py-1.5 text-xs border border-border rounded-radius-sm hover:bg-bg-hover"
          >
            取消
          </button>
          <button
            type="button"
            disabled={!canSubmit}
            onClick={() => void handleSubmit()}
            data-testid="quick-add-submit"
            className="px-3 py-1.5 text-xs bg-primary text-text-inverse rounded-radius-sm hover:bg-primary-hover disabled:opacity-40 disabled:cursor-not-allowed"
          >
            创建
          </button>
        </div>
      }
    >
      <div className="space-y-3">
        <input
          type="text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              void handleSubmit();
            } else if (e.key === 'Escape') {
              handleClose();
            }
          }}
          autoFocus
          placeholder="如：明天下午3点 交报告 !高 #工作"
          aria-label="快速添加待办输入"
          data-testid="quick-add-input"
          className="w-full px-3 py-2 text-sm border border-border rounded-radius-sm bg-background focus:outline-none focus:border-primary placeholder:text-text-muted"
        />

        <div
          className="flex flex-wrap items-center gap-1.5 min-h-[1.5rem]"
          data-testid="quick-add-preview"
        >
          {parsed.dueAt && (
            <span className="flex items-center gap-1 px-1.5 py-0.5 text-ui-xs rounded-full border border-border text-text-muted">
              <Calendar className="w-3 h-3" />
              {formatDuePreview(parsed.dueAt)}
            </span>
          )}
          {parsed.priority && (
            <span className="flex items-center gap-1 px-1.5 py-0.5 text-ui-xs rounded-full border border-border text-text-muted">
              <Flag className="w-3 h-3" />
              优先级 {PRIORITY_LABEL[parsed.priority]}
            </span>
          )}
          {parsed.tags.map((tag) => (
            <span
              key={tag}
              className="flex items-center gap-0.5 px-1.5 py-0.5 text-ui-xs rounded-full bg-blue-50 dark:bg-blue-900/20 text-blue-600"
            >
              <Hash className="w-3 h-3" />
              {tag}
            </span>
          ))}
          {!hasPreview && text.trim().length > 0 && (
            <span className="text-ui-xs text-text-muted">未识别到时间/优先级/标签，直接创建</span>
          )}
        </div>

        <p className="text-ui-xs text-text-muted">
          支持：今天 / 明天 / 后天 / 周一 / 1月20日 / 下午3点 / 9点半 · !高 !中 !低 · #标签
        </p>
      </div>
    </Modal>
  );
}
