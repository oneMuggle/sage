// src/features/office/DocxBlobPreview.tsx
//
// 2026-10-29: 聊天产物面板的 Word 高保真预览容器。
// 与 /office 页共用 renderDocxDataUrl 渲染 + DOMPurify 消毒链路，
// 输入为后端 artifact content 返回的 docx 原文 data URL。

import { useEffect, useRef, useState } from 'react';

import { renderDocxDataUrl } from './DocxNativePreview';

export interface DocxBlobPreviewProps {
  dataUrl: string;
  /** 渲染失败时通知父组件回退结构化视图；容器本身不显示错误文案 */
  onError?: () => void;
}

export function DocxBlobPreview({ dataUrl, onError }: DocxBlobPreviewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [state, setState] = useState<'loading' | 'ok' | 'error'>('loading');
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;

  useEffect(() => {
    let cancelled = false;
    setState('loading');
    (async () => {
      try {
        const container = containerRef.current;
        if (!container) return;
        await renderDocxDataUrl(container, dataUrl);
        if (!container.children.length) {
          // docx-preview 对加密/异常文档可能"成功"但不产出任何节点，
          // 空白板不如回退结构化视图。
          throw new Error('docx render produced no nodes');
        }
        if (!cancelled) setState('ok');
      } catch {
        if (!cancelled) {
          setState('error');
          onErrorRef.current?.();
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [dataUrl]);

  return (
    <div
      ref={containerRef}
      data-testid="docx-blob-preview"
      data-state={state}
      className="docx-preview bg-white text-black rounded border border-border p-3 overflow-auto"
    />
  );
}
