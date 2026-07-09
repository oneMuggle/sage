import { DndContext, PointerSensor, useSensor, useSensors, type DragEndEvent } from '@dnd-kit/core';
import { SortableContext, arrayMove, verticalListSortingStrategy } from '@dnd-kit/sortable';

import { sortSiderItemsByStoredOrder } from '../../shared/lib/dnd/siderOrder';
import { SortableSessionItem } from '../../shared/lib/dnd/sortableItem';
import type { Session } from '../../shared/lib/store';

import { SessionItem } from './SessionItem';

interface SortableSessionListProps {
  sessions: Session[];
  order: string[];
  currentSessionId: string | null;
  onSelect: (sessionId: string) => void;
  onDelete: (sessionId: string) => void;
  onOrderChange: (next: string[]) => void;
}

const ACTIVATION_DISTANCE = 8; // px — 避免点击 item 误触发拖拽

export function SortableSessionList({
  sessions,
  order,
  currentSessionId,
  onSelect,
  onDelete,
  onOrderChange,
}: SortableSessionListProps) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: ACTIVATION_DISTANCE } }),
  );

  const sorted = sortSiderItemsByStoredOrder(sessions, order);

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const fromIndex = order.indexOf(String(active.id));
    const toIndex = order.indexOf(String(over.id));
    if (fromIndex < 0 || toIndex < 0) return;
    onOrderChange(arrayMove(order, fromIndex, toIndex));
  };

  if (sorted.length === 0) {
    return <div className="px-3 py-4 text-xs text-text-muted text-center">暂无对话记录</div>;
  }

  return (
    <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
      <SortableContext items={order} strategy={verticalListSortingStrategy}>
        <ul className="flex flex-col gap-0.5">
          {sorted.map((session) => (
            <SortableSessionItem
              key={session.id}
              id={session.id}
              label={`选择会话 ${session.title}`}
            >
              <SessionItem
                session={session}
                isActive={session.id === currentSessionId}
                onSelect={() => onSelect(session.id)}
                onDelete={() => onDelete(session.id)}
              />
            </SortableSessionItem>
          ))}
        </ul>
      </SortableContext>
    </DndContext>
  );
}
