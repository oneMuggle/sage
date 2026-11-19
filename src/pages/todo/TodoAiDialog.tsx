/**
 * TodoAiDialog — AI 简报 / 周回顾弹窗（阶段 2）。
 *
 * mode='brief'  → GET /todos/brief（今日三条行动建议）
 * mode='weekly' → GET /todos/weekly-review（完成情况 / 拖延提醒 / 下周建议）
 * 打开时生成一次；提供「重新生成」。
 */
import { Loader2, RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import { todoClient } from '../../shared/api/todoClient';
import { Modal } from '../../shared/ui';

interface TodoAiDialogProps {
  isOpen: boolean;
  mode: 'brief' | 'weekly';
  onClose: () => void;
}

const TITLES: Record<TodoAiDialogProps['mode'], string> = {
  brief: 'AI 今日简报',
  weekly: '周回顾',
};

export function TodoAiDialog({ isOpen, mode, onClose }: TodoAiDialogProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [content, setContent] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result =
        mode === 'brief' ? await todoClient.dailyBrief() : await todoClient.weeklyReview();
      setContent(result.content);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [mode]);

  useEffect(() => {
    if (!isOpen) return;
    void load();
  }, [isOpen, load]);

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={TITLES[mode]}
      footer={
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            data-testid="todo-ai-refresh"
            className="flex items-center gap-1 px-3 py-1.5 text-xs border border-border rounded-radius-sm hover:bg-bg-hover disabled:opacity-40"
          >
            <RefreshCw className="w-3 h-3" />
            重新生成
          </button>
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-xs bg-primary text-text-inverse rounded-radius-sm hover:bg-primary-hover"
          >
            关闭
          </button>
        </div>
      }
    >
      <div className="min-h-[6rem]">
        {loading && (
          <div className="flex items-center gap-2 text-sm text-text-muted py-6 justify-center">
            <Loader2 className="w-4 h-4 animate-spin" />
            正在生成…
          </div>
        )}
        {!loading && error && (
          <p className="text-xs text-red-600 py-4" role="alert" data-testid="todo-ai-error">
            {error}
          </p>
        )}
        {!loading && !error && (
          <div
            className="text-sm text-text whitespace-pre-wrap leading-relaxed"
            data-testid="todo-ai-content"
          >
            {content}
          </div>
        )}
      </div>
    </Modal>
  );
}
