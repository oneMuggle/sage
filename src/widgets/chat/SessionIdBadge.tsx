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
      className="px-1.5 py-0.5 text-[10px] font-mono rounded bg-bg-hover text-text-tertiary hover:text-text-secondary hover:bg-border/50 transition-colors"
      title={copied ? '已复制完整 ID' : `点击复制完整会话 ID: ${sessionId}`}
    >
      {copied ? '✓ 已复制' : `#${shortId}`}
    </button>
  );
}
