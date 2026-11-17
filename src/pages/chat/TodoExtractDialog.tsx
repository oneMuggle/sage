/**
 * TodoExtractDialog — 从当前会话提炼待办候选，确认后批量创建（阶段 2）。
 *
 * 流程：打开 → 调 extract 端点（LLM 结构化输出，不落库）→ 候选清单
 * （可勾选、可改标题）→ 确认 → batch_create（带 source_type/source_ref 反向链接）。
 */
import { Loader2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { todoClient } from '../../shared/api/todoClient';
import type { CreateTodoInput, TodoExtractCandidate } from '../../shared/api/types';
import { Modal } from '../../shared/ui';

interface TodoExtractDialogProps {
  isOpen: boolean;
  sessionId: string;
  onClose: () => void;
}

const PRIORITY_LABEL: Record<string, string> = {
  high: '高',
  medium: '中',
  low: '低',
};

export function TodoExtractDialog({ isOpen, sessionId, onClose }: TodoExtractDialogProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<TodoExtractCandidate[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!isOpen || !sessionId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setCandidates([]);
    setSelected(new Set());

    todoClient
      .extractFromSession(sessionId)
      .then((result) => {
        if (cancelled) return;
        setCandidates(result.candidates);
        setSelected(new Set(result.candidates.map((_, index) => index)));
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [isOpen, sessionId]);

  const toggle = (index: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  };

  const updateTitle = (index: number, title: string) => {
    setCandidates((prev) =>
      prev.map((candidate, idx) => (idx === index ? { ...candidate, title } : candidate)),
    );
  };

  const handleConfirm = async () => {
    const items: CreateTodoInput[] = candidates
      .filter((_, index) => selected.has(index))
      .filter((candidate) => candidate.title.trim().length > 0)
      .map((candidate) => ({
        title: candidate.title.trim(),
        ...(candidate.due_at ? { due_at: candidate.due_at } : {}),
        ...(candidate.priority ? { priority: candidate.priority } : {}),
        ...(candidate.tags.length > 0 ? { tags: candidate.tags } : {}),
        source_type: 'chat',
        source_ref: sessionId,
      }));

    if (items.length === 0) {
      onClose();
      return;
    }

    setBusy(true);
    try {
      const created = await todoClient.batchCreate(items);
      toast.success(`已创建 ${created.length} 条待办`);
      onClose();
    } catch (err) {
      toast.error(`创建待办失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="从对话提取待办"
      footer={
        <div className="flex items-center justify-between">
          <span className="text-ui-xs text-text-muted">已选 {selected.size} 条</span>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 text-xs border border-border rounded-radius-sm hover:bg-bg-hover"
            >
              取消
            </button>
            <button
              type="button"
              disabled={busy || loading || selected.size === 0}
              onClick={() => void handleConfirm()}
              data-testid="todo-extract-confirm"
              className="px-3 py-1.5 text-xs bg-primary text-text-inverse rounded-radius-sm hover:bg-primary-hover disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {busy ? '创建中…' : '创建所选待办'}
            </button>
          </div>
        </div>
      }
    >
      <div className="space-y-2 min-h-[6rem]">
        {loading && (
          <div className="flex items-center gap-2 text-sm text-text-muted py-6 justify-center">
            <Loader2 className="w-4 h-4 animate-spin" />
            正在分析对话…
          </div>
        )}
        {!loading && error && (
          <p className="text-xs text-red-600 py-4" role="alert" data-testid="todo-extract-error">
            {error}
          </p>
        )}
        {!loading && !error && candidates.length === 0 && (
          <p className="text-sm text-text-muted py-6 text-center">没有从这段对话中提炼出行动项</p>
        )}
        {!loading &&
          !error &&
          candidates.map((candidate, index) => (
            <div
              key={index}
              className="flex items-start gap-2 px-2 py-1.5 border border-border rounded-radius-sm"
            >
              <input
                type="checkbox"
                checked={selected.has(index)}
                onChange={() => toggle(index)}
                className="mt-1.5 w-3.5 h-3.5 rounded border-border accent-primary cursor-pointer"
                aria-label={`选择 ${candidate.title}`}
              />
              <div className="flex-1 min-w-0">
                <input
                  type="text"
                  value={candidate.title}
                  onChange={(e) => updateTitle(index, e.target.value)}
                  aria-label="待办标题"
                  className="w-full text-sm bg-transparent focus:outline-none border-b border-transparent focus:border-primary"
                />
                <div className="flex flex-wrap items-center gap-1.5 mt-1">
                  {candidate.due_at && (
                    <span className="text-ui-xs text-text-muted">⏰ {candidate.due_at}</span>
                  )}
                  {candidate.priority && (
                    <span className="text-ui-xs text-text-muted">
                      优先级 {PRIORITY_LABEL[candidate.priority] ?? candidate.priority}
                    </span>
                  )}
                  {candidate.tags.map((tag) => (
                    <span
                      key={tag}
                      className="px-1.5 py-0.5 text-ui-xs rounded-full bg-blue-50 dark:bg-blue-900/20 text-blue-600"
                    >
                      #{tag}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          ))}
      </div>
    </Modal>
  );
}
