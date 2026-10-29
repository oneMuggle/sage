import {
  Brain,
  Copy,
  GitBranch,
  History,
  Pencil,
  Quote,
  RefreshCw,
  ThumbsDown,
  ThumbsUp,
  Trash2,
} from 'lucide-react';

import type { TranslationKey } from '../../shared/lib/i18n';
import type { Message } from '../../shared/lib/store';
import type { ContextMenuItemSpec } from '../../shared/ui/ContextMenu/types';

export type MessageMenuMessage = Pick<Message, 'id' | 'role' | 'content'>;

export interface MessageContextMenuParams {
  message: MessageMenuMessage;
  t: (key: TranslationKey) => string;
  isStreaming?: boolean;
  /** 右键打开菜单时落在气泡内的选中文本（无选区为 null）。 */
  selectionText?: string | null;
  onCopySelection: () => void | Promise<void>;
  onQuoteSelection: () => void;
  onCopy: () => void | Promise<void>;
  onCopyMarkdown: () => void | Promise<void>;
  onQuote?: () => void;
  onEditResend?: () => void;
  onRegenerate?: () => void;
  onFeedback?: (feedback: 'up' | 'down') => void;
  onFork?: () => void;
  onRewind?: () => void;
  onSaveToMemory?: () => void;
  onDelete?: () => void | Promise<void>;
}

/**
 * 消息气泡右键菜单（对标 Cherry Studio 的选区感知消息菜单）。
 *
 * - 有选中文本时，顶部提供「复制选区 / 引用选区到输入框」（无选区时不显示）；
 * - 用户消息与助手消息的可用动作集合不同（编辑重发 / 重新生成）；
 * - 流式生成期间只允许复制，生成类与删除动作禁用；
 * - 所有动作都复用 MessageActionBar / useChatMessageActions 的既有 handler。
 */
export function buildMessageContextMenuItems({
  message,
  t,
  isStreaming = false,
  selectionText = null,
  onCopySelection,
  onQuoteSelection,
  onCopy,
  onCopyMarkdown,
  onQuote,
  onEditResend,
  onRegenerate,
  onFeedback,
  onFork,
  onRewind,
  onSaveToMemory,
  onDelete,
}: MessageContextMenuParams): ContextMenuItemSpec[] {
  const isUser = message.role === 'user';
  const isAssistant = message.role === 'assistant';
  const hasContent = Boolean((message.content ?? '').trim());
  const hasSelection = Boolean(selectionText?.trim());
  const items: ContextMenuItemSpec[] = [];

  if (hasSelection) {
    items.push(
      {
        id: 'copy-selection',
        label: t('contextMenu.common.selectionCopy'),
        icon: Copy,
        onSelect: onCopySelection,
      },
      {
        id: 'quote-selection',
        label: t('contextMenu.common.selectionQuote'),
        icon: Quote,
        disabled: isStreaming || !onQuote,
        onSelect: onQuoteSelection,
      },
      { id: 'sep-selection', kind: 'separator' },
    );
  }

  items.push(
    {
      id: 'copy',
      label: t('contextMenu.common.copy'),
      icon: Copy,
      disabled: !hasContent,
      onSelect: onCopy,
    },
    {
      id: 'copy-markdown',
      label: t('contextMenu.message.copyMarkdown'),
      icon: Copy,
      disabled: !hasContent,
      onSelect: onCopyMarkdown,
    },
  );

  if (onQuote) {
    items.push({
      id: 'quote',
      label: t('contextMenu.message.quote'),
      icon: Quote,
      disabled: isStreaming,
      onSelect: onQuote,
    });
  }

  if (isUser && onEditResend) {
    items.push({
      id: 'edit-resend',
      label: t('contextMenu.message.editResend'),
      icon: Pencil,
      disabled: isStreaming,
      onSelect: onEditResend,
    });
  }

  if (isAssistant && onRegenerate) {
    items.push({
      id: 'regenerate',
      label: t('contextMenu.message.regenerate'),
      icon: RefreshCw,
      disabled: isStreaming,
      onSelect: onRegenerate,
    });
  }

  if (onFeedback) {
    items.push(
      {
        id: 'feedback-up',
        label: t('contextMenu.message.feedbackUp'),
        icon: ThumbsUp,
        disabled: isStreaming,
        onSelect: () => onFeedback('up'),
      },
      {
        id: 'feedback-down',
        label: t('contextMenu.message.feedbackDown'),
        icon: ThumbsDown,
        disabled: isStreaming,
        onSelect: () => onFeedback('down'),
      },
    );
  }

  if (onFork) {
    items.push({
      id: 'fork',
      label: t('contextMenu.message.fork'),
      icon: GitBranch,
      disabled: isStreaming,
      onSelect: onFork,
    });
  }

  if (onRewind) {
    items.push({
      id: 'rewind',
      label: t('contextMenu.message.rewind'),
      icon: History,
      disabled: isStreaming,
      onSelect: onRewind,
    });
  }

  if (onSaveToMemory) {
    items.push({
      id: 'save-to-memory',
      label: t('contextMenu.message.saveToMemory'),
      icon: Brain,
      disabled: isStreaming,
      onSelect: onSaveToMemory,
    });
  }

  if (onDelete) {
    items.push(
      { id: 'sep-delete', kind: 'separator' },
      {
        id: 'delete',
        label: t('contextMenu.message.delete'),
        icon: Trash2,
        destructive: true,
        disabled: isStreaming,
        onSelect: onDelete,
      },
    );
  }

  return items;
}
