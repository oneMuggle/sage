import { useEffect, useRef } from 'react';

import type {
  ConversationMessage,
  SuggestionCardData,
} from '../../../entities/office/officeWorkspaceStore';
import { fillTemplate } from '../../../shared/lib/fillTemplate';
import { useI18n, type TranslationKey } from '../../../shared/lib/i18n';

export interface ConversationAreaProps {
  messages: ConversationMessage[];
  pending: boolean;
  onApply: (messageId: string, suggestion: SuggestionCardData) => void;
  onSkip: (messageId: string, suggestionId: string) => void;
}

export function ConversationArea({
  messages,
  pending: _pending,
  onApply,
  onSkip,
}: ConversationAreaProps): JSX.Element {
  const { t } = useI18n();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = bottomRef.current;
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ block: 'end' });
    }
  }, [messages.length]);

  if (messages.length === 0) {
    return (
      <div
        data-testid="office-ai-conversation"
        className="flex flex-1 items-center justify-center p-6 text-sm text-text-muted"
      >
        {t('office.ai.sidebar.empty')}
      </div>
    );
  }

  return (
    <div data-testid="office-ai-conversation" className="flex-1 space-y-3 overflow-y-auto p-3">
      {messages.map((msg) => (
        <div key={msg.id} data-testid={`office-ai-message-${msg.id}`}>
          <div className="mb-1 text-xs font-medium text-text-secondary">{msg.role}</div>
          <div className="whitespace-pre-wrap text-sm text-text">{msg.content}</div>

          {msg.role === 'assistant' && <CopyButton text={msg.content} t={t} />}

          {msg.attachments?.map((suggestion) => (
            <SuggestionCard
              key={suggestion.id}
              messageId={msg.id}
              suggestion={suggestion}
              onApply={onApply}
              onSkip={onSkip}
              t={t}
            />
          ))}
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}

function CopyButton({
  text,
  t,
}: {
  text: string;
  t: (key: TranslationKey) => string;
}): JSX.Element {
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      /* clipboard unavailable */
    }
  };

  return (
    <button
      type="button"
      className="mt-1 text-xs text-text-muted hover:text-text"
      onClick={handleCopy}
    >
      {t('office.ai.sidebar.copy')}
    </button>
  );
}

function SuggestionCard({
  messageId,
  suggestion,
  onApply,
  onSkip,
  t,
}: {
  messageId: string;
  suggestion: SuggestionCardData;
  onApply: (messageId: string, suggestion: SuggestionCardData) => void;
  onSkip: (messageId: string, suggestionId: string) => void;
  t: (key: TranslationKey) => string;
}): JSX.Element {
  const statusLabel =
    suggestion.applied === 'applied'
      ? t('office.ai.audit.applied')
      : suggestion.applied === 'skipped'
        ? t('office.ai.audit.skipped')
        : null;

  return (
    <div
      data-testid={`office-ai-suggestion-${suggestion.id}`}
      className="mt-2 rounded border border-border bg-bg-subtle p-2 text-xs"
    >
      <div className="mb-1 font-medium text-text-secondary">
        {fillTemplate(t('office.ai.audit.paragraph'), {
          index: String(suggestion.paraIndex + 1),
        })}
      </div>
      <div className="mb-1 text-text-muted line-through">{suggestion.originalText}</div>
      <div className="mb-2 text-text">{suggestion.suggestedText}</div>
      {statusLabel ? (
        <span className="text-text-muted">{statusLabel}</span>
      ) : (
        <div className="flex gap-2">
          <button
            type="button"
            className="rounded bg-accent px-2 py-0.5 text-accent-foreground"
            onClick={() => onApply(messageId, suggestion)}
          >
            {t('office.ai.sidebar.apply')}
          </button>
          <button
            type="button"
            className="rounded px-2 py-0.5 text-text-muted hover:bg-surface-hover"
            onClick={() => onSkip(messageId, suggestion.id)}
          >
            {t('office.ai.audit.skip')}
          </button>
        </div>
      )}
    </div>
  );
}
