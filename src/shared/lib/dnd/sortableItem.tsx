import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { GripVertical } from 'lucide-react';
import type { CSSProperties, ReactNode } from 'react';

import { useI18n } from '../i18n';

interface SortableSessionItemProps {
  id: string;
  label: string;
  disabled?: boolean;
  children: ReactNode;
}

/**
 * 包装任意 session item,使之在 dnd-kit SortableContext 内可拖拽。
 * - 拖拽手柄是一个带 aria-label 的按钮(屏幕阅读器友好)
 * - 父节点接收 transform / transition 样式,实现平滑动画
 * - isDragging 时降低不透明度,提示用户该项被拖动
 *
 * 必须在 <DndContext> + <SortableContext> 内使用。
 */
export function SortableSessionItem({ id, label, disabled, children }: SortableSessionItemProps) {
  const { t } = useI18n();
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id,
    disabled,
  });

  const style: CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : 1,
  };

  return (
    <div ref={setNodeRef} style={style} aria-label={label} className="flex items-center">
      <button
        type="button"
        {...attributes}
        {...listeners}
        aria-label={t('sider.drag_handle')}
        title={t('sider.drag_handle')}
        className="inline-flex items-center justify-center w-5 h-5 mr-1 cursor-grab active:cursor-grabbing text-muted hover:text-text"
      >
        <GripVertical className="w-3.5 h-3.5" />
      </button>
      {children}
    </div>
  );
}
