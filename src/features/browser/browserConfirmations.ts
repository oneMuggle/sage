/**
 * 待确认项的对话归属筛选（服务端已按对话过滤，前端做兜底）。
 *
 * 从 BrowserPanel 抽出以控制单文件体积（架构棘轮 800 行红线）。
 */

import {
  fetchPendingConfirmations,
  type BrowserPendingConfirmation,
} from '../../shared/api/browserControlClient';

/**
 * 待确认项归属判定：
 * - 带 conversation_id：必须与本对话一致；
 * - 旧条目（无对话归属）：回退按本对话名下的浏览器实例过滤，绝不认领其他会话。
 */
export function acceptsPending(
  item: BrowserPendingConfirmation,
  conversationId: string | null,
  target: string | null,
): boolean {
  if (!conversationId) return true;
  if (item.conversation_id) return item.conversation_id === conversationId;
  return !!target && item.session_id === target;
}

/**
 * 拉取并筛选本对话的待确认项。
 *
 * 有对话即按对话轮询（HTTP 出网确认项没有浏览器实例也可见）；
 * 无对话退化为按实例过滤的旧行为；两者都没有则直接返回 null。
 */
export async function loadPendingFor(
  conversationId: string | null,
  target: string | null,
): Promise<BrowserPendingConfirmation | null> {
  if (!target && !conversationId) return null;
  const items = await fetchPendingConfirmations(target ?? undefined, conversationId ?? undefined);
  return items.find((item) => acceptsPending(item, conversationId, target)) ?? null;
}
