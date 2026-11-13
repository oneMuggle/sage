/**
 * DesignIterationChat — 对话框式迭代：提交 feedback 触发后端重新生成。
 */
import { Loader2, Send } from 'lucide-react';
import { useState } from 'react';

import { useDesignStore } from '../../entities/design/designStore';
import { useI18n } from '../../shared/lib/i18n';

interface DesignIterationChatProps {
  projectId: string;
}

export function DesignIterationChat({ projectId }: DesignIterationChatProps) {
  const { t } = useI18n();
  const iterate = useDesignStore((s) => s.iterate);
  const loading = useDesignStore((s) => s.loadingProject);
  const error = useDesignStore((s) => s.errorProject);
  const currentArtifact = useDesignStore((s) => s.currentArtifact);

  const [feedback, setFeedback] = useState('');
  const [history, setHistory] = useState<string[]>([]);

  const handleSend = async () => {
    const text = feedback.trim();
    if (!text || loading) return;
    setHistory((prev) => [...prev, text]);
    setFeedback('');
    await iterate(projectId, text);
  };

  return (
    <aside className="flex h-full min-h-0 flex-col rounded-lg border border-border bg-surface">
      <div className="border-b border-border px-3 py-2 text-ui-sm font-medium text-text">
        {t('design.detail.send')}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2 space-y-2">
        <p className="text-ui-xs text-text-tertiary">{t('design.detail.iterationHint')}</p>
        {history.map((entry, index) => (
          <div
            key={`${entry}-${index}`}
            className="ml-auto max-w-[92%] rounded-lg rounded-br-sm bg-accent/10 px-3 py-2 text-ui-sm text-text"
          >
            {entry}
          </div>
        ))}
        {loading && (
          <div className="flex items-center gap-1.5 text-ui-xs text-text-secondary">
            <Loader2 className="w-3 h-3 animate-spin" />
            {t('design.detail.sending')}
          </div>
        )}
        {!loading && currentArtifact && (
          <p className="text-ui-xs text-text-tertiary">
            {t('design.detail.version').replace('{version}', String(currentArtifact.version))}
          </p>
        )}
        {error && <p className="text-ui-xs text-red-500">{error}</p>}
      </div>

      <div className="border-t border-border p-2">
        <textarea
          value={feedback}
          onChange={(event) => setFeedback(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
              event.preventDefault();
              void handleSend();
            }
          }}
          rows={3}
          placeholder={t('design.detail.iterationHint')}
          className="w-full resize-none rounded-md border border-border bg-surface px-2 py-1.5 text-ui-sm outline-none focus:border-accent"
        />
        <div className="mt-2 flex justify-end">
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded-md bg-accent px-3 py-1.5 text-ui-xs text-white disabled:opacity-40"
            disabled={loading || feedback.trim().length === 0}
            onClick={() => void handleSend()}
          >
            {loading ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <Send className="w-3 h-3" />
            )}
            {loading ? t('design.detail.sending') : t('design.detail.send')}
          </button>
        </div>
      </div>
    </aside>
  );
}
