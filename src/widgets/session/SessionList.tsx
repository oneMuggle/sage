import type { Session } from '../../shared/lib/store';

import { SessionItem } from './SessionItem';

interface SessionListProps {
  sessions: Session[];
  currentSessionId: string | null;
  onSelect: (sessionId: string) => void;
  onDelete: (sessionId: string) => void;
  /** U4': 重命名回调(可选——缺省时 SessionItem 不渲染重命名入口) */
  onRename?: (sessionId: string, title: string) => Promise<void>;
  /** F12: 消息内容命中计数(会话 id → 命中条数;缺省不显示徽标) */
  messageHitsBySession?: Map<string, number>;
  /** 手动归档（缺省时不渲染入口） */
  onArchive?: (sessionId: string) => void;
  /** 恢复归档（缺省时不渲染入口） */
  onUnarchive?: (sessionId: string) => void;
}

export function formatSessionListMarkdown(
  sessions: ReadonlyArray<Session>,
  currentSessionId: string | null = null,
): string {
  const lines = [
    '# 会话列表摘要 (Session List)',
    '',
    `- **会话总数**: ${sessions.length}`,
    `- **当前激活会话**: ${currentSessionId || '无'}`,
  ];
  if (sessions.length === 0) {
    lines.push('', '_暂无对话记录_');
  } else {
    lines.push('', '## 会话明细');
    for (const s of sessions) {
      const activeTag = s.id === currentSessionId ? ' [当前]' : '';
      const pinTag = s.is_pinned ? ' [置顶]' : '';
      lines.push(`- **${s.title}** (\`${s.id}\`)${activeTag}${pinTag} — 消息数 ${s.message_count}`);
    }
  }
  return lines.join('\n');
}

export function formatSessionListJson(
  sessions: ReadonlyArray<Session>,
  currentSessionId: string | null = null,
): string {
  return JSON.stringify(
    {
      exportedAt: new Date().toISOString(),
      currentSessionId,
      total: sessions.length,
      sessions,
    },
    null,
    2,
  );
}

/**
 * 会话列表渲染组件。
 *
 * 历史沿革: 早期版本包了 @dnd-kit 拖拽层,用户拖拽顺序持久化到 localStorage
 * 覆盖后端默认序。2026-09-21 改为完全依赖后端排序:置顶 > 活跃(running/suspended)
 * > 时间降序。前端不再接收 order prop,也无 onOrderChange,排序由后端
 * `SessionRepository.list()` 在 SQL 层完成。
 */
export function SessionList({
  sessions,
  currentSessionId,
  onSelect,
  onDelete,
  onRename,
  messageHitsBySession,
  onArchive,
  onUnarchive,
}: SessionListProps) {
  if (sessions.length === 0) {
    return <div className="px-3 py-4 text-xs text-text-muted text-center">暂无对话记录</div>;
  }

  /* v8 ignore start */

  /* v8 ignore stop */

  return (
    <ul className="flex flex-col gap-0.5" data-testid="session-list">
      <li className="flex items-center justify-end gap-1 px-2 py-0.5 text-ui-2xs text-text-muted"></li>
      {sessions.map((session) => (
        <SessionItem
          key={session.id}
          session={session}
          isActive={session.id === currentSessionId}
          onSelect={() => onSelect(session.id)}
          onDelete={() => onDelete(session.id)}
          onRename={onRename}
          messageHits={messageHitsBySession?.get(session.id)}
          onArchive={onArchive ? () => onArchive(session.id) : undefined}
          onUnarchive={onUnarchive ? () => onUnarchive(session.id) : undefined}
        />
      ))}
    </ul>
  );
}
