import type { Session } from '../../shared/lib/store';

import { SessionItem } from './SessionItem';

interface SortableSessionListProps {
  sessions: Session[];
  currentSessionId: string | null;
  onSelect: (sessionId: string) => void;
  onDelete: (sessionId: string) => void;
  /** U4': 重命名回调(可选——缺省时 SessionItem 不渲染重命名入口) */
  onRename?: (sessionId: string, title: string) => Promise<void>;
  /** F12: 消息内容命中计数(会话 id → 命中条数;缺省不显示徽标) */
  messageHitsBySession?: Map<string, number>;
}

/**
 * 会话列表渲染组件。
 *
 * 历史沿革: 早期版本包了 @dnd-kit 拖拽层(故文件名仍叫 SortableSessionList),
 * 用户拖拽顺序持久化到 localStorage 覆盖后端默认序。2026-09-21 改为完全依赖
 * 后端排序:置顶 > 活跃(running/suspended) > 时间降序。前端不再接收 order prop,
 * 也无 onOrderChange,排序由后端 `SessionRepository.list()` 在 SQL 层完成。
 */
export function SortableSessionList({
  sessions,
  currentSessionId,
  onSelect,
  onDelete,
  onRename,
  messageHitsBySession,
}: SortableSessionListProps) {
  if (sessions.length === 0) {
    return <div className="px-3 py-4 text-xs text-text-muted text-center">暂无对话记录</div>;
  }

  return (
    <ul className="flex flex-col gap-0.5">
      {sessions.map((session) => (
        <SessionItem
          key={session.id}
          session={session}
          isActive={session.id === currentSessionId}
          onSelect={() => onSelect(session.id)}
          onDelete={() => onDelete(session.id)}
          onRename={onRename}
          messageHits={messageHitsBySession?.get(session.id)}
        />
      ))}
    </ul>
  );
}
