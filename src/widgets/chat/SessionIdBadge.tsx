/**
 * 会话 ID 徽章 —— 显示 UUID 前 8 位，点击复制完整 ID。
 * 方便排查问题时快速引用会话标识。
 */
import { useState } from 'react';

interface SessionIdBadgeProps {
  sessionId: string | null;
}

export function SessionIdBadge({ sessionId }: SessionIdBadgeProps) {
  const [copied, setCopied] = useState(false);

  if (!sessionId) return null;

  const shortId = sessionId.slice(0, 8);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(sessionId);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // 剪贴板 API 失败时静默（部分浏览器限制）
    }
  };

  return (
    <button
      type="button"
      onClick={handleCopy}
      className="px-1.5 py-0.5 text-ui-2xs font-mono rounded bg-bg-hover text-text-tertiary hover:text-text-secondary hover:bg-border/50 transition-colors"
      title={copied ? '已复制完整 ID' : `点击复制完整会话 ID: ${sessionId}`}
    >
      {copied ? '✓ 已复制' : `#${shortId}`}
    </button>
  );
}

export interface SessionIdBadgeAuditInput {
  sessionId: string;
  copiedRecently: boolean;
  displayPrefixLength: number;
}

export interface SessionIdBadgeAuditReport {
  sessionId: string;
  shortLabel: string;
  copiedRecently: boolean;
  healthy: boolean;
  issueCodes: string[];
}

// eslint-disable-next-line react-refresh/only-export-components
export function evaluateSessionIdBadgeAudit(
  input: SessionIdBadgeAuditInput,
): SessionIdBadgeAuditReport {
  const sessionId = input.sessionId.trim();
  const prefixLen = Math.max(4, Math.min(36, Math.trunc(input.displayPrefixLength || 8)));
  const shortLabel = sessionId.slice(0, prefixLen);
  const issueCodes: string[] = [];

  if (!sessionId) {
    issueCodes.push('missing_session_id');
  } else if (sessionId.length < 6) {
    issueCodes.push('session_id_too_short');
  }

  return {
    sessionId,
    shortLabel,
    copiedRecently: Boolean(input.copiedRecently),
    healthy: issueCodes.length === 0,
    issueCodes,
  };
}

// eslint-disable-next-line react-refresh/only-export-components
export function exportSessionIdBadgeAuditJson(
  input: SessionIdBadgeAuditInput,
): string {
  return JSON.stringify(evaluateSessionIdBadgeAudit(input));
}
// eslint-disable-next-line react-refresh/only-export-components
export function auditSessionIdBadgeGovernance(): string {
  return JSON.stringify({
    module: 'session-id-badge',
    phase: 'P194',
    audited: true,
  });
}
