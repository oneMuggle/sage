import { useEffect, useRef, useState } from 'react';

import type {
  ConversationMessage,
  SuggestionCardData,
} from '../../../entities/office/officeWorkspaceStore';
import { useI18n } from '../../../shared/lib/i18n';

import { InstructionEditCard } from './InstructionEditCard';

export interface ConversationAreaProps {
  messages: ConversationMessage[];
  pending: boolean;
  onApply: (messageId: string, suggestion: SuggestionCardData) => void;
  onSkip: (messageId: string, suggestionId: string) => void;
  /** When provided, the last pending-assistant-message renders the apply-all button. */
  onApplyAll?: (messageId: string) => void;
}

export function ConversationArea({
  messages,
  pending,
  onApply,
  onSkip,
  onApplyAll,
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

  // R18: only the LAST assistant message whose attachments contain at least one
  // `pending` card is allowed to render the apply-all button, so the testid
  // `office-ai-audit-apply-all` is unique across the whole conversation.
  const lastPendingAssistantId = findLastPendingAssistantId(messages);

  return (
    <div data-testid="office-ai-conversation" className="flex-1 space-y-3 overflow-y-auto p-3">
      {messages.map((msg) => (
        <MessageRow
          key={msg.id}
          msg={msg}
          pending={pending}
          isLastPendingAssistant={msg.id === lastPendingAssistantId}
          onApply={onApply}
          onApplyAll={onApplyAll}
          onSkip={onSkip}
        />
      ))}
      <div ref={bottomRef} />
    </div>
  );
}

function MessageRow({
  msg,
  pending,
  isLastPendingAssistant,
  onApply,
  onApplyAll,
  onSkip,
}: {
  msg: ConversationMessage;
  pending: boolean;
  isLastPendingAssistant: boolean;
  onApply: (messageId: string, suggestion: SuggestionCardData) => void;
  onApplyAll?: (messageId: string) => void;
  onSkip: (messageId: string, suggestionId: string) => void;
}): JSX.Element {
  const attachments = msg.attachments ?? [];
  const hasAttachments = attachments.length > 0;

  return (
    <div key={msg.id} data-testid={`office-ai-message-${msg.id}`}>
      <div className="mb-1 text-xs font-medium text-text-secondary">{msg.role}</div>
      <div className="whitespace-pre-wrap text-sm text-text">{msg.content}</div>

      {msg.role === 'assistant' && <CopyButton text={msg.content} />}

      {hasAttachments ? (
        <InstructionEditCard
          messageId={msg.id}
          suggestions={attachments}
          busy={pending}
          onApply={onApply}
          onSkip={onSkip}
          onApplyAll={onApplyAll && isLastPendingAssistant ? () => onApplyAll(msg.id) : undefined}
        />
      ) : null}
    </div>
  );
}

function findLastPendingAssistantId(messages: ConversationMessage[]): string | null {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const msg = messages[i];
    if (msg.role !== 'assistant' || !msg.attachments || msg.attachments.length === 0) continue;
    const hasPending = msg.attachments.some((a) => a.applied === 'pending');
    if (hasPending) return msg.id;
  }
  return null;
}

function CopyButton({ text }: { text: string }): JSX.Element {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
  const timeoutRef = useRef<number | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (timeoutRef.current !== null) {
        window.clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      /* clipboard unavailable */
      return;
    }
    if (!mountedRef.current) {
      return;
    }
    setCopied(true);
    if (timeoutRef.current !== null) {
      window.clearTimeout(timeoutRef.current);
    }
    timeoutRef.current = window.setTimeout(() => {
      if (mountedRef.current) {
        setCopied(false);
      }
    }, 2000);
  };

  return (
    <button
      type="button"
      className="mt-1 text-xs text-text-muted hover:text-text"
      onClick={handleCopy}
    >
      {copied ? t('office.ai.sidebar.copied') : t('office.ai.sidebar.copy')}
    </button>
  );
}
