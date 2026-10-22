/**
 * Task 5 (2026-09-17): 话题分隔线 —— 在聊天流中标记"上下文已在此处重置"。
 * 居中文字 + 两侧水平线的经典分隔线样式。
 */
export function TopicSeparator({ content }: { content?: string | null }) {
  return (
    <div className="flex items-center my-4 text-xs text-text-secondary select-none">
      <div className="flex-1 border-t border-border" />
      <span className="px-3 whitespace-nowrap">
        {content || '上下文已在此处重置'}
      </span>
      <div className="flex-1 border-t border-border" />
    </div>
  );
}

export interface TopicSeparatorAuditInput {
  topicTitle: string;
  timestampMs: number;
  messageCountBefore: number;
}

export interface TopicSeparatorAuditReport {
  topicTitle: string;
  hasValidTimestamp: boolean;
  messageCountBefore: number;
  healthy: boolean;
  issueCodes: string[];
}

// eslint-disable-next-line react-refresh/only-export-components
export function evaluateTopicSeparatorAudit(
  input: TopicSeparatorAuditInput,
): TopicSeparatorAuditReport {
  const topicTitle = input.topicTitle.trim();
  const hasValidTimestamp = Number.isFinite(input.timestampMs) && input.timestampMs > 0;
  const messageCountBefore = Math.max(0, Math.trunc(input.messageCountBefore));
  const issueCodes: string[] = [];

  if (!topicTitle) {
    issueCodes.push('empty_topic_separator_title');
  }
  if (!hasValidTimestamp) {
    issueCodes.push('invalid_topic_separator_timestamp');
  }

  return {
    topicTitle,
    hasValidTimestamp,
    messageCountBefore,
    healthy: issueCodes.length === 0,
    issueCodes,
  };
}

// eslint-disable-next-line react-refresh/only-export-components
export function exportTopicSeparatorAuditJson(
  input: TopicSeparatorAuditInput,
): string {
  return JSON.stringify(evaluateTopicSeparatorAudit(input));
}
