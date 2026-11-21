/**
 * 计划待批准状态的轻量持久化。
 *
 * PM2 的 `planApprovalFor` 只存在于 `useChat` 组件 state：切换会话还能恢复，
 * 但 renderer 重载（刷新/崩溃恢复）后"计划已生成，待批准"的批准条会消失，
 * 用户不知道计划还在等着确认。这里用一个会话级标记补齐重载恢复 ——
 * 只记录"该会话有待批准计划"，计划内容本身来自已落库的消息。
 */

const KEY_PREFIX = 'sage:plan-approval-pending:';

function storageKey(sessionId: string): string {
  return `${KEY_PREFIX}${sessionId}`;
}

/** 该会话是否有待批准的计划（localStorage 不可用时视为无）。 */
export function isPlanApprovalPending(sessionId: string | null): boolean {
  if (!sessionId) return false;
  try {
    return window.localStorage.getItem(storageKey(sessionId)) === '1';
  } catch {
    return false;
  }
}

/** 标记/清除该会话的"待批准计划"状态。 */
export function setPlanApprovalPending(sessionId: string | null, pending: boolean): void {
  if (!sessionId) return;
  try {
    if (pending) {
      window.localStorage.setItem(storageKey(sessionId), '1');
    } else {
      window.localStorage.removeItem(storageKey(sessionId));
    }
  } catch {
    // localStorage 拒绝（隐私模式/配额）时退化为不持久化，不影响本次会话内行为。
  }
}
