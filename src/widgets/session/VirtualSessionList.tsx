import { useVirtualizer } from '@tanstack/react-virtual';
import { useRef } from 'react';

import type { Session } from '../../shared/lib/store';

import { SessionItem } from './SessionItem';

/** 根据时间将消息分组为: 今天/昨天/本周/更早 */
function getSessionGroup(timestamp: number): string {
  const now = new Date();
  const date = new Date(timestamp);
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - 86400000);
  const weekStart = new Date(today.getTime() - today.getDay() * 86400000);

  if (date >= today) return '今天';
  if (date >= yesterday) return '昨天';
  if (date >= weekStart) return '本周';
  return '更早';
}

interface GroupedSession {
  type: 'group';
  label: string;
}

interface FlatSession {
  type: 'session';
  session: Session;
}

type ListItem = GroupedSession | FlatSession;

interface VirtualSessionListProps {
  sessions: Session[];
  currentSessionId: string | null;
  onSelect: (sessionId: string) => void;
  onDelete: (sessionId: string) => void;
  maxHeight?: string;
}

export function VirtualSessionList({
  sessions,
  currentSessionId,
  onSelect,
  onDelete,
  maxHeight = 'calc(100vh - 320px)',
}: VirtualSessionListProps) {
  const parentRef = useRef<HTMLDivElement>(null);

  // 按时间排序 (pin 优先, 然后按更新时间降序)
  const sorted = [...sessions].sort((a, b) => {
    if (a.is_pinned && !b.is_pinned) return -1;
    if (!a.is_pinned && b.is_pinned) return 1;
    return (b.last_message_at ?? b.updated_at) - (a.last_message_at ?? a.updated_at);
  });

  // 构建扁平列表 (含分组头)
  const items: ListItem[] = [];
  let lastGroup = '';

  for (const session of sorted) {
    const ts = session.last_message_at ?? session.updated_at;
    const group = getSessionGroup(ts);
    if (group !== lastGroup) {
      items.push({ type: 'group', label: group });
      lastGroup = group;
    }
    items.push({ type: 'session', session });
  }

  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => parentRef.current,
    estimateSize: (index) => (items[index].type === 'group' ? 28 : 52),
    overscan: 5,
  });

  if (items.length === 0) {
    return <div className="px-3 py-4 text-xs text-text-muted text-center">暂无对话记录</div>;
  }

  return (
    <div ref={parentRef} className="overflow-y-auto" style={{ maxHeight, minHeight: 0 }}>
      <div
        style={{
          height: `${virtualizer.getTotalSize()}px`,
          width: '100%',
          position: 'relative',
        }}
      >
        {virtualizer.getVirtualItems().map((virtualRow) => {
          const item = items[virtualRow.index];

          if (item.type === 'group') {
            return (
              <div
                key={`group-${item.label}`}
                className="text-[11px] font-semibold uppercase tracking-wide text-muted px-3 py-1 sticky top-0 bg-surface"
                style={{
                  position: 'absolute',
                  top: virtualRow.start,
                  left: 0,
                  width: '100%',
                  height: `${virtualRow.size}px`,
                }}
              >
                {item.label}
              </div>
            );
          }

          return (
            <div
              key={item.session.id}
              style={{
                position: 'absolute',
                top: virtualRow.start,
                left: 0,
                width: '100%',
                height: `${virtualRow.size}px`,
              }}
            >
              <SessionItem
                session={item.session}
                isActive={item.session.id === currentSessionId}
                onSelect={() => onSelect(item.session.id)}
                onDelete={() => onDelete(item.session.id)}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}
