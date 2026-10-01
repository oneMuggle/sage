import { useCallback, useEffect, useRef, useState } from 'react';

// UX-IA R3 批次 B：侧栏改为「56px rail + 内容列」两段式，width 语义仍是**总宽**
// （Layout 的 wrapper 与拖拽手柄按它算，未改动），内容列宽度 = width - 56。
// 因此边界整体上移：旧的 220~360 在扣掉 rail 后只剩 164~304px 内容列，
// 装不下会话标题。存量落在新界外的宽度会被视为越界并回落到默认值。
const SIDEBAR_MIN = 260;
const SIDEBAR_MAX = 480;
const SIDEBAR_DEFAULT = 300;
const STORAGE_KEY = 'sidebar-width';

export function useResizableSidebar() {
  const [width, setWidth] = useState<number>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        const parsed = Number(saved);
        if (!Number.isNaN(parsed) && parsed >= SIDEBAR_MIN && parsed <= SIDEBAR_MAX) {
          return parsed;
        }
      }
    } catch {
      // localStorage unavailable
    }
    return SIDEBAR_DEFAULT;
  });

  const isDraggingRef = useRef(false);

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    isDraggingRef.current = true;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  }, []);

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (!isDraggingRef.current) return;
      const newWidth = Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, e.clientX));
      setWidth(newWidth);
    };

    const onMouseUp = () => {
      if (!isDraggingRef.current) return;
      isDraggingRef.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      try {
        localStorage.setItem(STORAGE_KEY, String(width));
      } catch {
        // localStorage unavailable
      }
    };

    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    return () => {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };
  }, [width]);

  return { width, isDragging: isDraggingRef.current, onMouseDown };
}
