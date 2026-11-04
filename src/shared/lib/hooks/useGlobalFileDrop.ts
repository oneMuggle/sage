import { useEffect, useRef, useState } from 'react';

/**
 * P2 (2026-11-04): 全局文件拖放事件名。
 *
 * 页面级（Chat / Welcome）的 drop 监听器在捕获阶段拦截落在 composer 之外的
 * 拖放，派发该 CustomEvent；composer 组件（ChatInput / WelcomeInputCard）
 * 监听后把文件交给各自的 useFileUpload，与输入卡内 drop 行为完全一致。
 */
export const COMPOSER_DROP_EVENT = 'sage:composer-drop';

export interface GlobalFileDropOptions {
  /**
   * composer 根容器的 CSS 选择器 —— 落在该容器内的 drop 交由 composer 自己的
   * React `onDrop` 处理（保留已有的输入卡高亮反馈），本 hook 只接管容器外的拖放。
   */
  composerSelector: string;
}

/** 判断拖拽事件是否携带文件（纯文本拖拽不拦截，保留浏览器默认行为）。 */
function carriesFiles(e: DragEvent): boolean {
  // Electron 21 / Chromium 106 的 DataTransfer.types 是 DOMStringList，
  // 没有 Array.from 之外的 iterable 协议，统一转成数组判断。
  return Array.from(e.dataTransfer?.types ?? []).includes('Files');
}

/**
 * 页面级全局拖放。
 *
 * - 在 document 捕获阶段监听 dragenter/dragleave/dragover/drop，
 *   使"把文件拖到页面任意位置"都能被接收（对标 ChatGPT / Claude 的整页拖放）。
 * - 落在 `composerSelector` 内的 drop 不拦截，交给 composer 自己的 onDrop。
 * - 落在容器外的 drop 派发 {@link COMPOSER_DROP_EVENT}，由 composer 消费。
 *
 * @returns `isDragOver` —— 当前是否有含文件的拖拽悬停在页面上（用于全局遮罩）。
 */
export function useGlobalFileDrop({ composerSelector }: GlobalFileDropOptions): {
  isDragOver: boolean;
} {
  const [isDragOver, setIsDragOver] = useState(false);
  // dragenter/dragleave 在嵌套元素间会成对冒泡，用计数器抵消子元素带来的
  // 误增误减，避免遮罩闪烁。
  const dragCounterRef = useRef(0);

  useEffect(() => {
    const onDragEnter = (e: DragEvent) => {
      if (!carriesFiles(e)) return;
      e.preventDefault();
      dragCounterRef.current += 1;
      if (dragCounterRef.current === 1) setIsDragOver(true);
    };
    const onDragLeave = (e: DragEvent) => {
      if (!carriesFiles(e)) return;
      e.preventDefault();
      dragCounterRef.current = Math.max(0, dragCounterRef.current - 1);
      if (dragCounterRef.current === 0) setIsDragOver(false);
    };
    const onDragOver = (e: DragEvent) => {
      if (!carriesFiles(e)) return;
      e.preventDefault();
    };
    const onDrop = (e: DragEvent) => {
      if (!carriesFiles(e)) return;
      const composer = document.querySelector(composerSelector);
      if (composer && e.target && composer.contains(e.target as Node)) {
        // composer 内的 drop 由 composer 自己的 React onDrop 处理；这里放行。
        return;
      }
      e.preventDefault();
      e.stopPropagation();
      const files = Array.from(e.dataTransfer?.files ?? []);
      if (files.length === 0) return;
      window.dispatchEvent(new CustomEvent(COMPOSER_DROP_EVENT, { detail: { files } }));
      dragCounterRef.current = 0;
      setIsDragOver(false);
    };

    document.addEventListener('dragenter', onDragEnter, true);
    document.addEventListener('dragleave', onDragLeave, true);
    document.addEventListener('dragover', onDragOver, true);
    document.addEventListener('drop', onDrop, true);
    return () => {
      document.removeEventListener('dragenter', onDragEnter, true);
      document.removeEventListener('dragleave', onDragLeave, true);
      document.removeEventListener('dragover', onDragOver, true);
      document.removeEventListener('drop', onDrop, true);
    };
  }, [composerSelector]);

  return { isDragOver };
}
