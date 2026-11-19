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
  const messages = useDesignStore((s) => s.messages);

  const [feedback, setFeedback] = useState('');
  const [pending, setPending] = useState<string | null>(null);

  const handleSend = async () => {
    const text = feedback.trim();
    if (!text || loading) return;
    setPending(text);
    setFeedback('');
    try {
      await iterate(projectId, text);
    } finally {
      setPending(null);
    }
  };

  return (
    <aside className="flex h-full min-h-0 flex-col rounded-lg border border-border bg-surface">
      <div className="border-b border-border px-3 py-2 text-ui-sm font-medium text-text">
        {t('design.detail.send')}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2 space-y-2">
        <p className="text-ui-xs text-text-muted">{t('design.detail.iterationHint')}</p>
        {messages.map((message) =>
          message.role === 'user' ? (
            <div
              key={message.id}
              className="ml-auto max-w-[92%] rounded-lg rounded-br-sm bg-accent/10 px-3 py-2 text-ui-sm text-text"
            >
              {message.content}
            </div>
          ) : (
            <div
              key={message.id}
              className="max-w-[92%] rounded-lg rounded-bl-sm bg-bg-hover px-3 py-2 text-ui-xs text-text-secondary"
            >
              {message.artifact_version
                ? t('design.detail.version').replace(
                    '{version}',
                    String(message.artifact_version),
                  )
                : message.content}
            </div>
          ),
        )}
        {pending && (
          <div className="ml-auto max-w-[92%] rounded-lg rounded-br-sm bg-accent/10 px-3 py-2 text-ui-sm text-text">
            {pending}
          </div>
        )}
        {loading && (
          <div className="flex items-center gap-1.5 text-ui-xs text-text-secondary">
            <Loader2 className="w-3 h-3 animate-spin" />
            {t('design.detail.sending')}
          </div>
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
