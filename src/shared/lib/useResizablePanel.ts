/**
 * useResizablePanel — 通用面板宽度可调 hook（P0-3 UI 优化方案 2026-09-12）。
 *
 * - 初始宽度从 localStorage 读取（无值/越界则回落到 defaultWidth）
 * - 拖拽期间实时 clamp 到 [minWidth, maxWidth]
 * - 松手持久化到 localStorage；用 ref 读最新值避免 useEffect 闭包陷阱
 * - 拖拽期间禁用文本选择 + 光标锁定为 col-resize，松手恢复
 */
import { useCallback, useEffect, useRef, useState } from 'react';

interface Options {
  storageKey: string;
  minWidth: number;
  maxWidth: number;
  defaultWidth: number;
  /** 面板锚定在哪一侧：right = 面板右贴边、拖拽条在左边；left 反之。默认 right。 */
  anchor?: 'left' | 'right';
}

export function useResizablePanel({
  storageKey,
  minWidth,
  maxWidth,
  defaultWidth,
  anchor = 'right',
}: Options) {
  const [width, setWidth] = useState<number>(() => {
    try {
      const saved = localStorage.getItem(storageKey);
      if (saved) {
        const parsed = Number(saved);
        if (!Number.isNaN(parsed) && parsed >= minWidth && parsed <= maxWidth) {
          return parsed;
        }
      }
    } catch {
      // localStorage 不可用（SSR/隐私模式），回落默认值
    }
    return defaultWidth;
  });

  const isDraggingRef = useRef(false);
  const widthRef = useRef(width);
  widthRef.current = width;

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    isDraggingRef.current = true;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  }, []);

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (!isDraggingRef.current) return;
      // anchor=right → 面板右贴边, 拖拽条在左边 → 宽度 = viewport 右边缘 - 鼠标 x
      // anchor=left  → 面板左贴边, 拖拽条在右边 → 宽度 = 鼠标 x
      const viewportWidth = window.innerWidth;
      const raw = anchor === 'right' ? viewportWidth - e.clientX : e.clientX;
      const next = Math.min(maxWidth, Math.max(minWidth, raw));
      setWidth(next);
    };

    const onMouseUp = () => {
      if (!isDraggingRef.current) return;
      isDraggingRef.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      try {
        localStorage.setItem(storageKey, String(widthRef.current));
      } catch {
        // localStorage 不可用
      }
    };

    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    return () => {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };
  }, [anchor, maxWidth, minWidth, storageKey]);

  return { width, onMouseDown };
}
