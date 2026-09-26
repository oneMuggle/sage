/**
 * 对话阅读体验 C2（docs/mcp-chat-reading-nav-optimization.md §10.6）：回答版本切换。
 *
 * 只对会话的最后一轮生效。重新生成时后端在新回答首次落库前，把旧回答整轮归档为
 * 一个版本（失败时旧回答不动）；切换版本时当前回答归档、目标版本以新 id 恢复。
 */
import { backendRequest } from '../../shared/api/backendRequest';
import { isDemoMode } from '../../shared/api/demoFlag';
import type { Message } from '../../shared/lib/store';

export interface AnswerVersionSummary {
  /** 当前显示中的版本为 'current' */
  id: string;
  generated_at: number;
  preview: string;
  current: boolean;
}

export interface AnswerVersionList {
  anchor_id: string | null;
  total: number;
  /** 当前版本的序号（从 1 开始）；0 = 没有当前版本 */
  current_index: number;
  versions: AnswerVersionSummary[];
}

const sessionPath = (sessionId: string) =>
  `/api/v1/sessions/${encodeURIComponent(sessionId)}/answer-versions`;

export function fetchAnswerVersions(sessionId: string): Promise<AnswerVersionList> {
  return backendRequest<AnswerVersionList>({ path: sessionPath(sessionId), method: 'GET' });
}

export async function activateAnswerVersion(sessionId: string, versionId: string): Promise<void> {
  await backendRequest({
    path: `${sessionPath(sessionId)}/${encodeURIComponent(versionId)}/activate`,
    method: 'POST',
  });
}

/**
 * 最后一轮的锚点：assistantIndex 之前最近的 user 消息，且它之后没有别的 user 消息。
 * 返回锚点下标；不是最后一轮时返回 -1。
 */
export function lastTurnAnchorIndex(messages: readonly Message[], assistantIndex: number): number {
  let anchor = -1;
  for (let i = assistantIndex - 1; i >= 0; i--) {
    if (messages[i].role === 'user') {
      anchor = i;
      break;
    }
  }
  if (anchor < 0) return -1;
  return messages.slice(anchor + 1).some((m) => m.role === 'user') ? -1 : anchor;
}

interface RegenerateInPlaceDeps {
  removeMessage: (id: string) => void;
  sendMessage: (
    content: string,
    sessionId: string,
    officeRefs: undefined,
    orchestrationMode: undefined,
    opts: { regenerateOf: string },
  ) => Promise<unknown>;
}

/**
 * 最后一轮原位重新生成：本地先移除旧回答，再以 regenerateOf 重发锚点问题。流结束后
 * 前端会按服务端对账，所以失败时旧回答会重新出现。更早的轮次或演示模式返回 false，
 * 调用方沿用分叉会话的旧行为。
 */
export function regenerateInPlace(
  messages: readonly Message[],
  assistantIndex: number,
  sessionId: string,
  deps: RegenerateInPlaceDeps,
): boolean {
  if (isDemoMode()) return false;
  const anchorIndex = lastTurnAnchorIndex(messages, assistantIndex);
  if (anchorIndex < 0) return false;
  const anchor = messages[anchorIndex];
  for (const message of messages.slice(anchorIndex + 1)) deps.removeMessage(message.id);
  void deps.sendMessage(anchor.content, sessionId, undefined, undefined, {
    regenerateOf: anchor.id,
  });
  return true;
}
