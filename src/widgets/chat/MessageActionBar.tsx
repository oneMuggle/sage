import {
  Brain,
  Check,
  Copy,
  GitBranch,
  History,
  MoreHorizontal,
  Pencil,
  Quote,
  RefreshCw,
  ThumbsDown,
  ThumbsUp,
} from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import { useI18n } from '../../shared/lib/i18n';
import type { Message as MessageType } from '../../shared/lib/store';
import { TwoStepDelete } from '../sidebar/TwoStepDelete';

import { AnswerVersionSwitcher } from './AnswerVersionSwitcher';
import { GenerationStatsBadge } from './GenerationStatsBadge';
import { ReadAloudButton } from './ReadAloudButton';

export interface MessageActionBarProps {
  message: MessageType;
  isStreaming?: boolean;
  onFeedback?: (messageId: string, feedback: 'up' | 'down') => void;
  onFork?: (messageId: string) => void;
  onRewind?: (messageId: string) => void;
  onEditResend?: (messageId: string) => void;
  onRegenerate?: (messageId: string) => void;
  onDelete?: (messageId: string) => void;
  onQuote?: (message: MessageType) => void;
  onSaveToMemory?: (message: MessageType) => void;
  onAnswerVersionChange?: () => void;
}

export function MessageActionBar({
  message,
  isStreaming,
  onFeedback,
  onFork,
  onRewind,
  onEditResend,
  onRegenerate,
  onDelete,
  onQuote,
  onSaveToMemory,
  onAnswerVersionChange,
}: MessageActionBarProps) {
  const { t } = useI18n();
  const isUser = message.role === 'user';
  const isAssistant = message.role === 'assistant';

  const canFork = Boolean(onFork) && (isUser || isAssistant);
  const canRewind = Boolean(onRewind) && (isUser || isAssistant) && !isStreaming;
  const canEditResend = Boolean(onEditResend) && isUser;
  const canRegenerate = Boolean(onRegenerate) && isAssistant && !isStreaming;
  const canCopy =
    (isUser || isAssistant) && Boolean((message.content ?? '').trim()) && !isStreaming;
  const canDelete = Boolean(onDelete) && (isUser || isAssistant) && !isStreaming;
  const canQuote = Boolean(onQuote) && (isUser || isAssistant);
  const canSaveToMemory = Boolean(onSaveToMemory) && (isUser || isAssistant);

  const hasSecondaryActions = canFork || canRewind || canSaveToMemory || canDelete;

  const [copied, setCopied] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const copiedResetRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (copiedResetRef.current !== null) clearTimeout(copiedResetRef.current);
    },
    [],
  );

  const copyToClipboard = () => {
    navigator.clipboard.writeText(message.content);
    setCopied(true);
    if (copiedResetRef.current !== null) clearTimeout(copiedResetRef.current);
    copiedResetRef.current = setTimeout(() => {
      copiedResetRef.current = null;
      setCopied(false);
    }, 1500);
  };

  if (
    !(
      canCopy ||
      onFeedback ||
      canFork ||
      canRewind ||
      canEditResend ||
      canDelete ||
      canRegenerate ||
      canQuote ||
      canSaveToMemory
    )
  ) {
    return null;
  }

  return (
    <div className="group/msg-actions flex items-center gap-1 mt-2 pt-2 border-t border-border">
      <div className="flex items-center gap-1" data-testid="message-primary-actions">
        {isAssistant && onAnswerVersionChange && !isStreaming && (
          <AnswerVersionSwitcher
            sessionId={message.session_id}
            messageId={message.id}
            onChanged={onAnswerVersionChange}
          />
        )}
        {canCopy && (
          <button
            onClick={copyToClipboard}
            className="p-1 rounded hover:bg-bg-hover"
            title={t('chat.copy')}
            aria-label={t('chat.copy')}
            data-testid="copy-message"
          >
            {copied ? <Check className="w-4 h-4 text-primary" /> : <Copy className="w-4 h-4" />}
          </button>
        )}
        {canCopy && isAssistant && (
          <ReadAloudButton messageId={message.id} content={message.content} />
        )}
        {onFeedback && (
          <>
            <button
              onClick={() => onFeedback(message.id, 'up')}
              className="p-1 rounded hover:bg-bg-hover"
              title="有帮助"
              aria-label="有帮助"
            >
              <ThumbsUp className="w-4 h-4" />
            </button>
            <button
              onClick={() => onFeedback(message.id, 'down')}
              className="p-1 rounded hover:bg-bg-hover"
              title="没帮助"
              aria-label="没帮助"
            >
              <ThumbsDown className="w-4 h-4" />
            </button>
          </>
        )}
        {canRegenerate && (
          <button
            onClick={() => onRegenerate?.(message.id)}
            className="p-1 rounded hover:bg-bg-hover"
            title={t('chat.regenerate')}
            aria-label={t('chat.regenerate')}
            data-testid="regenerate-message"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        )}
        {canEditResend && (
          <button
            onClick={() => onEditResend?.(message.id)}
            className="p-1 rounded hover:bg-bg-hover"
            title={t('chat.edit_resend')}
            aria-label={t('chat.edit_resend')}
            data-testid="edit-resend"
          >
            <Pencil className="w-4 h-4" />
          </button>
        )}
        {canQuote && (
          <button
            onClick={() => onQuote?.(message)}
            className="p-1 rounded hover:bg-bg-hover"
            title={t('chat.quote_to_chat')}
            aria-label={t('chat.quote_to_chat')}
            data-testid="quote-message"
          >
            <Quote className="w-4 h-4" />
          </button>
        )}
      </div>

      {hasSecondaryActions && (
        <>
          <button
            type="button"
            onClick={() => setMoreOpen((v) => !v)}
            className="p-1 rounded text-muted hover:text-text hover:bg-bg-hover transition-colors"
            title="更多操作"
            aria-label="更多操作"
            aria-expanded={moreOpen}
            data-testid="message-more-actions-toggle"
          >
            <MoreHorizontal className="w-4 h-4" />
          </button>
          <div
            className={
              moreOpen
                ? 'flex items-center gap-1'
                : 'hidden group-hover/msg-actions:flex items-center gap-1'
            }
            data-testid="message-secondary-actions"
          >
            {canFork && (
              <button
                onClick={() => onFork?.(message.id)}
                className="p-1 rounded hover:bg-bg-hover"
                title={t('chat.fork_from_here')}
                aria-label={t('chat.fork_from_here')}
                data-testid="fork-message"
              >
                <GitBranch className="w-4 h-4" />
              </button>
            )}
            {canRewind && (
              <button
                onClick={() => onRewind?.(message.id)}
                className="p-1 rounded hover:bg-bg-hover"
                title={t('chat.rewind')}
                aria-label={t('chat.rewind')}
                data-testid="rewind-message"
              >
                <History className="w-4 h-4" />
              </button>
            )}
            {canSaveToMemory && (
              <button
                onClick={() => onSaveToMemory?.(message)}
                className="p-1 rounded hover:bg-bg-hover"
                title={t('chat.save_to_memory')}
                aria-label={t('chat.save_to_memory')}
                data-testid="save-to-memory"
              >
                <Brain className="w-4 h-4" />
              </button>
            )}
            {canDelete && (
              <TwoStepDelete
                data-testid="delete-message"
                onConfirm={() => onDelete?.(message.id)}
                label={t('chat.delete_message')}
                armedLabel={t('chat.delete_message_confirm')}
                className="p-1"
              />
            )}
          </div>
        </>
      )}

      {isAssistant && !isStreaming && (
        <GenerationStatsBadge stats={message.generation_stats} />
      )}
    </div>
  );
}
