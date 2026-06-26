import { Trash2, Pin } from 'lucide-react';

import type { Session } from '../../shared/lib/store';

interface SessionItemProps {
  session: Session;
  isActive: boolean;
  onSelect: () => void;
  onDelete: () => void;
}

export function SessionItem({ session, isActive, onSelect, onDelete }: SessionItemProps) {
  const handleDelete = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (confirm('确定要删除这个会话吗？')) {
      onDelete();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onSelect();
    }
  };

  return (
    <div
      role="button"
      tabIndex={0}
      data-testid="session-item"
      data-session-id={session.id}
      aria-label={`选择会话 ${session.title}`}
      aria-pressed={isActive}
      onClick={onSelect}
      onKeyDown={handleKeyDown}
      className={`
        group flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer
        transition-colors focus:outline-none focus:ring-2 focus:ring-primary
        ${isActive ? 'bg-primary/10 text-primary' : 'hover:bg-bg-hover'}
      `}
    >
      {/* 会话标题 */}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium truncate">{session.title}</p>
        <p className="text-xs text-muted">{new Date(session.updated_at).toLocaleDateString()}</p>
      </div>

      {/* 操作按钮 */}
      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        {session.is_pinned && <Pin className="w-4 h-4 text-primary" />}
        <button
          onClick={handleDelete}
          className="p-1 rounded hover:bg-error/10 text-error"
          title="删除"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
