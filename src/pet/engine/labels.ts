/**
 * Status / session labels for the pet panel and bubble.
 *
 * The pet renderer is standalone (no main app i18n provider), so this is a
 * small zh/en dictionary based on navigator.language.
 */

import type { PetSessionSummaryBridge, PetSnapshotBridge } from '../../shared/types/electron-api';

function isZh(): boolean {
  return typeof navigator !== 'undefined' && navigator.language.toLowerCase().startsWith('zh');
}

export function isChinese(): boolean {
  return isZh();
}

const TOOL_VERBS: Record<string, { zh: string; en: string }> = {
  bash: { zh: '跑命令', en: 'running a command' },
  edit: { zh: '改代码', en: 'editing code' },
  read: { zh: '翻文件', en: 'reading files' },
  web: { zh: '上网查', en: 'searching the web' },
  mcp: { zh: '用外部工具', en: 'using an external tool' },
  office: { zh: '写文档', en: 'working on a document' },
  other: { zh: '执行工具', en: 'using a tool' },
};

export function sessionLabel(title: string | null, sessionId: string | null): string {
  const trimmed = title?.trim();
  if (trimmed) return trimmed;
  if (!sessionId) return isZh() ? '空闲' : 'Idle';
  const shortId = sessionId.slice(0, 8);
  return isZh() ? `会话 ${shortId}` : `Session ${shortId}`;
}

export function toolLabel(detail: string | null, toolName: string | null): string | null {
  if (toolName) return toolName;
  if (!detail) return null;
  const verb = TOOL_VERBS[detail] ?? TOOL_VERBS.other;
  return isZh() ? verb.zh : verb.en;
}

export function statusLabel(
  action: string,
  detail: string | null,
  toolName: string | null,
): string {
  switch (action) {
    case 'waiting':
      return isZh() ? '等待审批' : 'Waiting for approval';
    case 'error':
      return isZh() ? '出错' : 'Error';
    case 'done':
      return isZh() ? '已完成' : 'Done';
    case 'acting': {
      const verb = TOOL_VERBS[detail ?? 'other'] ?? TOOL_VERBS.other;
      return isZh() ? `正在${verb.zh}` : `Working — ${verb.en}`;
    }
    case 'retry':
      return isZh() ? '重试中' : 'Retrying';
    case 'thinking':
      return isZh() ? '思考中' : 'Thinking';
    case 'observing':
      return isZh() ? '整理结果' : 'Processing results';
    case 'sleeping':
      return isZh() ? '休息中' : 'Sleeping';
    case 'idle':
      return isZh() ? '空闲' : 'Idle';
    default:
      return toolLabel(detail, toolName) ?? (isZh() ? '运行中' : 'Running');
  }
}

export function progressLabel(kind: string | null): string {
  if (kind === 'plan') return isZh() ? '步骤' : 'Steps';
  return isZh() ? '待办' : 'Todos';
}

export function taskStatusLabel(status: string): string {
  const labels: Record<string, { zh: string; en: string }> = {
    queued: { zh: '排队中', en: 'Queued' },
    running: { zh: '运行中', en: 'Running' },
    awaiting_approval: { zh: '等待审批', en: 'Waiting' },
    paused: { zh: '已暂停', en: 'Paused' },
    failed: { zh: '失败', en: 'Failed' },
    succeeded: { zh: '已完成', en: 'Done' },
    cancelled: { zh: '已取消', en: 'Cancelled' },
  };
  const label = labels[status];
  if (!label) return status;
  return isZh() ? label.zh : label.en;
}

export function taskKindLabel(kind: string): string {
  if (kind === 'office') return 'Office';
  if (kind === 'wiki') return 'Wiki';
  return isZh() ? '任务' : 'Task';
}

export function taskAction(status: string): string {
  if (status === 'awaiting_approval') return 'waiting';
  if (status === 'failed') return 'error';
  if (status === 'running' || status === 'queued' || status === 'paused') return 'acting';
  return 'idle';
}

const ACTIVE_ACTIONS = new Set(['thinking', 'acting', 'waiting', 'retry', 'observing']);

export function isActiveAction(action: string): boolean {
  return ACTIVE_ACTIONS.has(action);
}

export function statusGlyph(action: string): string {
  switch (action) {
    case 'waiting':
    case 'error':
      return '!';
    case 'done':
      return '✓';
    case 'acting':
      return '▶';
    case 'thinking':
      return '…';
    case 'retry':
      return '↻';
    case 'observing':
      return '◇';
    case 'sleeping':
      return 'z';
    default:
      return '·';
  }
}

export function relativeTime(timestamp: number | null, now = Date.now()): string {
  if (!timestamp || timestamp <= 0) return '';
  const seconds = Math.max(0, Math.round((now - timestamp) / 1000));
  if (seconds < 10) return isZh() ? '刚刚' : 'just now';
  if (seconds < 60) return isZh() ? `${seconds} 秒前` : `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return isZh() ? `${minutes} 分钟前` : `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  return isZh() ? `${hours} 小时前` : `${hours}h ago`;
}

export function formatTokens(tokens: number): string {
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(1)}M`;
  if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(1)}k`;
  return String(tokens);
}

export function contextPercent(used: number | null, max: number | null): number | null {
  if (!used || !max || max <= 0) return null;
  return Math.min(100, Math.max(0, Math.round((used / max) * 100)));
}

export function snapshotForPanel(snapshot: PetSnapshotBridge): PetSessionSummaryBridge | null {
  return snapshot.sessions[0] ?? null;
}
