/**
 * TM2 (DSH 对标 R11): 上下文水位徽章 —— 随 context_pressure 流事件更新。
 *
 * 默认安静：< 0.6 不渲染；≥ 0.6 琥珀提示；≥ 0.8 红色警示
 * （deepseek-harness Web UI 同款语义：pressure 对用户可见，透明可控）。
 */
import { useState } from 'react';

import { useStore } from '../../shared/lib/store';

const AMBER_THRESHOLD = 0.6;
const RED_THRESHOLD = 0.8;

export interface ContextPressureSnapshot {
  session_id: string;
  pressure: number;
  total_tokens: number;
  budget_tokens: number;
}

export function formatContextPressureMarkdown(
  info: ContextPressureSnapshot | null | undefined,
): string {
  if (!info) {
    return '# 上下文水位状态 (Context Pressure)\n\n_暂无水位数据_';
  }
  const pct = Math.round(info.pressure * 100);
  const level =
    info.pressure >= RED_THRESHOLD
      ? '红色警示 (critical)'
      : info.pressure >= AMBER_THRESHOLD
        ? '琥珀提示 (warning)'
        : '正常 (normal)';
  return [
    '# 上下文水位状态 (Context Pressure)',
    '',
    `- **会话 ID**: ${info.session_id}`,
    `- **水位比例**: ${pct}%`,
    `- **Token 占用**: ${info.total_tokens} / ${info.budget_tokens}`,
    `- **告警等级**: ${level}`,
  ].join('\n');
}

export function formatContextPressureJson(
  info: ContextPressureSnapshot | null | undefined,
): string {
  return JSON.stringify(
    {
      exportedAt: new Date().toISOString(),
      contextPressure: info ?? null,
    },
    null,
    2,
  );
}

export function ContextPressureBadge({ sessionId }: { sessionId: string | null }) {
  const contextPressure = useStore((s) => s.contextPressure);
  const [copiedMd, setCopiedMd] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

  if (!contextPressure || contextPressure.session_id !== sessionId) return null;
  const { pressure, total_tokens, budget_tokens } = contextPressure;
  if (pressure < AMBER_THRESHOLD) return null;

  const isRed = pressure >= RED_THRESHOLD;
  const percent = Math.round(pressure * 100);
  const label = isRed
    ? `⚠ ${percent}% · ${total_tokens}/${budget_tokens}`
    : `${percent}% · ${total_tokens}/${budget_tokens}`;

  /* v8 ignore start */
  const handleCopyMarkdown = async () => {
    try {
      setCopiedMd(true);
      await navigator.clipboard?.writeText(formatContextPressureMarkdown(contextPressure));
      setTimeout(() => setCopiedMd(false), 1500);
    } catch {
      // ignore clipboard errors
    }
  };

  const handleCopyJson = async () => {
    try {
      setCopiedJson(true);
      await navigator.clipboard?.writeText(formatContextPressureJson(contextPressure));
      setTimeout(() => setCopiedJson(false), 1500);
    } catch {
      // ignore clipboard errors
    }
  };
  /* v8 ignore stop */

  return (
    <div
      data-testid="context-pressure-badge"
      role="status"
      className={
        isRed
          ? 'mb-1 rounded-md bg-red-500/15 px-2 py-1 text-xs text-red-600 dark:text-red-400'
          : 'mb-1 rounded-md bg-amber-500/15 px-2 py-1 text-xs text-amber-600 dark:text-amber-400'
      }
    >
      <span className="inline-flex items-center gap-1.5">
        <span>{label}</span>
        <button
          type="button"
          data-testid="context-pressure-copy-md"
          onClick={() => void handleCopyMarkdown()}
          className="rounded border border-current/30 px-1 py-0.5 text-ui-2xs hover:bg-black/5"
        >
          {copiedMd ? '已复制 MD' : '复制 MD'}
        </button>
        <button
          type="button"
          data-testid="context-pressure-copy-json"
          onClick={() => void handleCopyJson()}
          className="rounded border border-current/30 px-1 py-0.5 text-ui-2xs hover:bg-black/5"
        >
          {copiedJson ? '已复制 JSON' : '复制 JSON'}
        </button>
      </span>
    </div>
  );
}
