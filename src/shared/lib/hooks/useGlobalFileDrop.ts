import { useEffect, useRef, useState } from 'react';

/**
 * 文件拖放事件名。页面级 hook（useGlobalFileDrop）在 drop 时派发，
 * composer 组件（ChatInput / WelcomeInputCard）监听后把文件交给各自的
 * useFileUpload —— 这是文件进入附件列表的**唯一通道**。
 */
export const COMPOSER_DROP_EVENT = 'sage:composer-drop';

/** 判断拖拽事件是否携带文件（纯文本拖拽不拦截，保留浏览器默认行为）。 */
function carriesFiles(e: DragEvent): boolean {
  // Electron 21 / Chromium 106 的 DataTransfer.types 是 DOMStringList，
  // 没有 Array.from 之外的 iterable 协议，统一转成数组判断。
  return Array.from(e.dataTransfer?.types ?? []).includes('Files');
}

/**
 * 页面级全局拖放（Chat 页与新对话页共用）。
 *
 * 2026-11-15 重写：本 hook 是拖放的唯一入口，不再区分 composer 内/外 ——
 * 任何含文件的 drop 都 preventDefault 并派发 {@link COMPOSER_DROP_EVENT}。
 * 旧实现按 composerSelector 分流 + 捕获阶段 stopPropagation，当 drop 目标是
 * 输入卡内覆盖层（不在 textarea 内）时 composer 的 React onDrop 永不执行，
 * `isDragOver` 无人复位，遮罩卡死且阻断输入。
 *
 * 复位路径：drop / dragend / 拖出窗口（dragleave 且 relatedTarget 为 null）
 * 一律清零，避免取消拖拽（Esc、拖出后松手）留下遮罩。
 */
export function useGlobalFileDrop(): { isDragOver: boolean } {
  const [isDragOver, setIsDragOver] = useState(false);
  // dragenter/dragleave 在嵌套元素间会成对冒泡，用计数器抵消子元素带来的
  // 误增误减，避免遮罩闪烁。
  const dragDepthRef = useRef(0);
  // dragenter 建立拖拽会话：dragleave 时 dataTransfer 在部分 Chromium 版本
  // 不可靠，不能每次现查 types —— 用会话标志判断"本次拖拽是否含文件"。
  const fileSessionRef = useRef(false);

  useEffect(() => {
    const reset = () => {
      dragDepthRef.current = 0;
      fileSessionRef.current = false;
      setIsDragOver(false);
    };

    const onDragEnter = (e: DragEvent) => {
      if (!carriesFiles(e)) return;
      e.preventDefault();
      fileSessionRef.current = true;
      dragDepthRef.current += 1;
      if (dragDepthRef.current === 1) setIsDragOver(true);
    };
    const onDragLeave = (e: DragEvent) => {
      if (!fileSessionRef.current) return;
      dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
      // relatedTarget 为 null = 指针离开了整个窗口 —— 计数器已不可信，直接复位。
      if (e.relatedTarget === null || dragDepthRef.current === 0) reset();
    };
    const onDragOver = (e: DragEvent) => {
      if (!carriesFiles(e) && !fileSessionRef.current) return;
      // 必须 preventDefault，浏览器才会把元素识别为可放置目标并触发 drop。
      e.preventDefault();
    };
    const onDrop = (e: DragEvent) => {
      if (!carriesFiles(e)) {
        reset();
        return;
      }
      // drop 完成时浏览器不会再为 drop target 触发 dragleave —— 无条件复位。
      e.preventDefault();
      const files = Array.from(e.dataTransfer?.files ?? []);
      reset();
      if (files.length === 0) return;
      window.dispatchEvent(new CustomEvent(COMPOSER_DROP_EVENT, { detail: { files } }));
    };
    const onDragEnd = () => reset();

    document.addEventListener('dragenter', onDragEnter, true);
    document.addEventListener('dragleave', onDragLeave, true);
    document.addEventListener('dragover', onDragOver, true);
    document.addEventListener('drop', onDrop, true);
    window.addEventListener('dragend', onDragEnd);
    return () => {
      document.removeEventListener('dragenter', onDragEnter, true);
      document.removeEventListener('dragleave', onDragLeave, true);
      document.removeEventListener('dragover', onDragOver, true);
      document.removeEventListener('drop', onDrop, true);
      window.removeEventListener('dragend', onDragEnd);
    };
  }, []);

  return { isDragOver };
}
