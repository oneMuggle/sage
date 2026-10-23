export { ChatInput } from './ChatInput';
export { InputCard } from './InputCard';
export type {
  InputCardProps,
  FileAttachmentType,
  ImageAttachmentType,
  KnowledgeRefType,
  KnowledgeDocType,
} from './InputCard';
export { MessageList } from './MessageList';
export { MemoryWriteHints } from './MemoryWriteHints';
export { Message } from './Message';
export { TopicSeparator } from './TopicSeparator';
export { ActiveAgentIndicator } from './ActiveAgentIndicator';
export { SubagentLivePanel } from './SubagentLivePanel';
export { RunSummaryPanel } from './RunSummaryPanel';
export { PendingQueueStrip } from './PendingQueueStrip';

export interface ChatWidgetBarrelAuditInput {
  exportedComponentCount: number;
  hasComposerExport: boolean;
  hasMessageListExport: boolean;
}

export interface ChatWidgetBarrelAuditReport {
  exportedComponentCount: number;
  hasComposerExport: boolean;
  hasMessageListExport: boolean;
  healthy: boolean;
  issueCodes: string[];
}

export function evaluateChatWidgetBarrelAudit(
  input: ChatWidgetBarrelAuditInput,
): ChatWidgetBarrelAuditReport {
  const exportedComponentCount = Math.max(0, Math.trunc(input.exportedComponentCount));
  const hasComposerExport = Boolean(input.hasComposerExport);
  const hasMessageListExport = Boolean(input.hasMessageListExport);
  const issueCodes: string[] = [];

  if (exportedComponentCount === 0) {
    issueCodes.push('empty_chat_widget_barrel');
  }
  if (!hasComposerExport) {
    issueCodes.push('missing_composer_export');
  }
  if (!hasMessageListExport) {
    issueCodes.push('missing_message_list_export');
  }

  return {
    exportedComponentCount,
    hasComposerExport,
    hasMessageListExport,
    healthy: issueCodes.length === 0,
    issueCodes,
  };
}

export function exportChatWidgetBarrelAuditJson(
  input: ChatWidgetBarrelAuditInput,
): string {
  return JSON.stringify(evaluateChatWidgetBarrelAudit(input));
}
