import type { Session } from './store';

/** 与后端 `SessionRepository.list()` 的活跃判定一致。 */
const ACTIVE_RUN_STATUSES = new Set(['running', 'suspended']);

export function isSessionActive(session: Pick<Session, 'run_status'>): boolean {
  return typeof session.run_status === 'string' && ACTIVE_RUN_STATUSES.has(session.run_status);
}

/**
 * 会话列表比较器，字段顺序严格对齐后端 SQL：
 *   `is_pinned DESC, run_status IN ('running','suspended') DESC, updated_at DESC`
 * 本地只在乐观更新（运行开始/新会话入列）时使用；常规顺序仍以服务端返回为准。
 */
export function compareSessions(a: Session, b: Session): number {
  if (a.is_pinned !== b.is_pinned) return a.is_pinned ? -1 : 1;
  const activeA = isSessionActive(a) ? 1 : 0;
  const activeB = isSessionActive(b) ? 1 : 0;
  if (activeA !== activeB) return activeB - activeA;
  return b.updated_at - a.updated_at;
}

/** 稳定排序并返回新数组（不原地修改）。 */
export function sortSessions(sessions: Session[]): Session[] {
  return [...sessions].sort(compareSessions);
}
