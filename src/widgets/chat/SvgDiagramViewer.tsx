// 可交互 SVG / 图片查看器 —— 消费 P1 富媒体引用（api_url）而非内联 base64。
// 交互模型与 MermaidDiagram 同构：拖拽平移、Ctrl+滚轮缩放、双击复位、
// 适应屏幕/实际大小、下载 PNG/SVG、全屏。区别在于对象是 <img>（不注入 HTML）。

import { Download, Expand, FileDown, Maximize2, RotateCcw, X, ZoomIn, ZoomOut } from 'lucide-react';
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

import { fetchMediaBlobUrl, resolveMediaUrl, revokeMediaBlobUrl } from '../../shared/api/mediaApi';

const ZOOM_MIN = 0.4;
const ZOOM_MAX = 3;
const ZOOM_STEP = 1.25;

const clampZoom = (z: number) => Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z));

function triggerDownload(url: string, filename: string): void {
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export interface SvgDiagramViewerProps {
  apiUrl: string;
  mimeType: string;
  title?: string;
  caption?: string;
}

function ToolButton({
  label,
  onClick,
  children,
  testid,
}: {
  label: string;
  onClick: () => void;
  children: ReactNode;
  testid?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      data-testid={testid}
      className="p-1 rounded text-muted hover:text-text hover:bg-bg-hover transition-colors"
    >
      {children}
    </button>
  );
}

export function SvgDiagramViewer({ apiUrl, mimeType, title, caption }: SvgDiagramViewerProps) {
  const [status, setStatus] = useState<'loading' | 'loaded' | 'error'>('loading');
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [fullscreen, setFullscreen] = useState(false);
  const [viewportEl, setViewportEl] = useState<HTMLDivElement | null>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const dragRef = useRef({ active: false, x: 0, y: 0 });

  // Electron 下 <img> 无法携带 local-auth Bearer 头 → 经 IPC 换取 blob: URL；
  // 浏览器 dev 无 bridge 时直接走 resolveMediaUrl。
  useEffect(() => {
    setStatus('loading');
    if (!window.electronAPI?.backendRequest) return;
    const mediaId = apiUrl.split('/').filter(Boolean).pop() ?? '';
    if (!mediaId) return;
    let cancelled = false;
    fetchMediaBlobUrl(mediaId, mimeType)
      .then((u) => {
        if (!cancelled) setBlobUrl(u);
      })
      .catch(() => {
        if (!cancelled) setStatus('error');
      });
    return () => {
      cancelled = true;
    };
  }, [apiUrl, mimeType]);

  useEffect(() => {
    return () => {
      if (blobUrl) revokeMediaBlobUrl(blobUrl);
    };
  }, [blobUrl]);

  useEffect(() => {
    if (!fullscreen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setFullscreen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [fullscreen]);

  // Ctrl+滚轮缩放 —— 原生非 passive 监听，才能拦掉浏览器自身页面缩放
  useEffect(() => {
    if (!viewportEl) return;
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey) return;
      e.preventDefault();
      setZoom((z) => clampZoom(+(z * (e.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP)).toFixed(3)));
    };
    viewportEl.addEventListener('wheel', onWheel, { passive: false });
    return () => viewportEl.removeEventListener('wheel', onWheel);
  }, [viewportEl]);

  const src = blobUrl ?? resolveMediaUrl(apiUrl);

  const zoomBy = useCallback((factor: number) => {
    setZoom((z) => clampZoom(+(z * factor).toFixed(3)));
  }, []);

  const resetView = useCallback(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }, []);

  const fitToScreen = useCallback(() => {
    const img = imgRef.current;
    if (!viewportEl || !img || viewportEl.clientWidth <= 0 || viewportEl.clientHeight <= 0) {
      resetView();
      return;
    }
    const w = img.naturalWidth || img.clientWidth;
    const h = img.naturalHeight || img.clientHeight;
    if (w <= 0 || h <= 0) {
      resetView();
      return;
    }
    const scale = Math.min(viewportEl.clientWidth / w, viewportEl.clientHeight / h);
    setZoom(clampZoom(+scale.toFixed(3)));
    setPan({ x: 0, y: 0 });
  }, [viewportEl, resetView]);

  const handlePointerDown = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    const clientX = Number.isFinite(e.clientX) ? e.clientX : 0;
    const clientY = Number.isFinite(e.clientY) ? e.clientY : 0;
    dragRef.current = { active: true, x: clientX, y: clientY };
    const el = e.currentTarget;
    if (typeof el.setPointerCapture === 'function' && e.pointerId !== undefined) {
      try {
        el.setPointerCapture(e.pointerId);
      } catch {
        // 旧内核/jsdom 不支持指针捕获 —— 事件仍在元素内冒泡
      }
    }
  }, []);

  const handlePointerMove = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag.active) return;
    const clientX = Number.isFinite(e.clientX) ? e.clientX : drag.x;
    const clientY = Number.isFinite(e.clientY) ? e.clientY : drag.y;
    const dx = clientX - drag.x;
    const dy = clientY - drag.y;
    drag.x = clientX;
    drag.y = clientY;
    if (dx === 0 && dy === 0) return;
    setPan((p) => ({ x: p.x + dx, y: p.y + dy }));
  }, []);

  const handlePointerUp = useCallback(() => {
    dragRef.current.active = false;
  }, []);

  const exportPng = useCallback(() => {
    const img = imgRef.current;
    if (!img) return;
    const el = new Image();
    el.onload = () => {
      const scale = 2;
      const w = Math.max(1, (el.naturalWidth || img.clientWidth || 800) * scale);
      const h = Math.max(1, (el.naturalHeight || img.clientHeight || 600) * scale);
      const canvas = document.createElement('canvas');
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(0, 0, w, h);
      ctx.drawImage(el, 0, 0, w, h);
      canvas.toBlob((blob) => {
        if (blob) triggerDownload(URL.createObjectURL(blob), 'diagram.png');
      }, 'image/png');
    };
    el.src = src;
  }, [src]);

  const exportSvg = useCallback(() => {
    void fetch(src)
      .then((r) => r.text())
      .then((text) => {
        const blob = new Blob([text], { type: 'image/svg+xml;charset=utf-8' });
        triggerDownload(URL.createObjectURL(blob), 'diagram.svg');
      })
      .catch(() => {
        // 下载失败静默（网络/权限问题），用户可重试
      });
  }, [src]);

  const transform =
    pan.x === 0 && pan.y === 0
      ? `scale(${zoom})`
      : `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`;

  const renderToolbar = (variant: 'hover' | 'bar') => (
    <div
      data-testid="svg-diagram-toolbar"
      className={
        variant === 'hover'
          ? 'absolute top-1 right-1 z-10 flex items-center gap-0.5 p-0.5 rounded bg-surface/95 border border-border shadow-sm opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity'
          : 'flex items-center gap-0.5 p-0.5 rounded bg-surface/95 border border-border'
      }
    >
      <ToolButton label="放大" onClick={() => zoomBy(ZOOM_STEP)} testid="svg-diagram-zoom-in">
        <ZoomIn className="w-3.5 h-3.5" />
      </ToolButton>
      <span
        data-testid="svg-diagram-zoom-label"
        className="text-ui-xs text-muted w-8 text-center tabular-nums"
      >
        {Math.round(zoom * 100)}%
      </span>
      <ToolButton label="缩小" onClick={() => zoomBy(1 / ZOOM_STEP)} testid="svg-diagram-zoom-out">
        <ZoomOut className="w-3.5 h-3.5" />
      </ToolButton>
      <ToolButton label="适应屏幕" onClick={fitToScreen} testid="svg-diagram-fit">
        <Maximize2 className="w-3.5 h-3.5" />
      </ToolButton>
      <ToolButton label="实际大小" onClick={resetView} testid="svg-diagram-actual-size">
        <RotateCcw className="w-3.5 h-3.5" />
      </ToolButton>
      <ToolButton label="下载 PNG" onClick={exportPng} testid="svg-diagram-download-png">
        <Download className="w-3.5 h-3.5" />
      </ToolButton>
      <ToolButton label="下载 SVG" onClick={exportSvg} testid="svg-diagram-download-svg">
        <FileDown className="w-3.5 h-3.5" />
      </ToolButton>
      {variant === 'hover' ? (
        <ToolButton
          label="全屏"
          onClick={() => setFullscreen(true)}
          testid="svg-diagram-fullscreen-open"
        >
          <Expand className="w-3.5 h-3.5" />
        </ToolButton>
      ) : (
        <ToolButton
          label="退出全屏"
          onClick={() => setFullscreen(false)}
          testid="svg-diagram-fullscreen-close"
        >
          <X className="w-3.5 h-3.5" />
        </ToolButton>
      )}
    </div>
  );

  const viewport = (
    <div
      ref={setViewportEl}
      data-testid="svg-diagram-viewport"
      className="overflow-hidden cursor-grab active:cursor-grabbing select-none rounded border border-border bg-white dark:bg-transparent"
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerUp}
      onPointerLeave={handlePointerUp}
      onDoubleClick={resetView}
    >
      {status === 'error' ? (
        <div
          data-testid="svg-diagram-error"
          className="flex w-full h-48 items-center justify-center gap-2 text-xs text-muted"
        >
          图表加载失败
          <a
            href={src}
            download
            className="px-2 py-0.5 rounded border border-border text-ui-2xs text-primary hover:bg-primary/10 transition-colors"
          >
            下载原文件
          </a>
        </div>
      ) : (
        <div className="relative min-h-[8rem]">
          {status === 'loading' && (
            <div
              data-testid="svg-diagram-skeleton"
              className="absolute inset-0 flex items-center justify-center text-xs text-muted"
            >
              加载图表…
            </div>
          )}
          <div
            style={{ transform, transformOrigin: 'top left' }}
            className="inline-block min-w-full"
          >
            <img
              ref={imgRef}
              src={src}
              alt={title ?? caption ?? '图表'}
              draggable={false}
              data-testid="svg-diagram-img"
              onLoad={() => setStatus('loaded')}
              onError={() => setStatus('error')}
              className={`max-w-none transition-opacity duration-300 ${
                status === 'loaded' ? 'opacity-100' : 'opacity-0'
              }`}
            />
          </div>
        </div>
      )}
    </div>
  );

  if (fullscreen) {
    return createPortal(
      <div
        data-testid="svg-diagram-fullscreen"
        className="fixed inset-0 z-[70] bg-black/90 flex flex-col"
        onClick={(e) => {
          if (e.target === e.currentTarget) setFullscreen(false);
        }}
      >
        <div className="flex items-center justify-end gap-1 p-2">{renderToolbar('bar')}</div>
        <div className="flex-1 overflow-hidden">{viewport}</div>
      </div>,
      document.body,
    );
  }

  return (
    <div data-testid="svg-diagram" className="relative group my-2">
      {renderToolbar('hover')}
      {viewport}
      {caption && (
        <div data-testid="svg-diagram-caption" className="mt-1 text-ui-2xs text-muted">
          {caption}
        </div>
      )}
    </div>
  );
}
