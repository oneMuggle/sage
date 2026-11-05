// src/widgets/chat/MermaidDiagram.tsx
//
// 2026-11-04 (rich-preview-rendering Task 3): Mermaid 交互式图表查看器。
//
// 从 MermaidBlock 抽出的独立组件（对标 ChatGPT / Claude / Typora 的图表交互）：
// - 拖拽平移（pointerdown → pointermove → pointerup）
// - Ctrl+滚轮缩放（0.4–3.0，步进 1.25；原生非 passive 监听，可 preventDefault）
// - 双击复位到实际大小（清空位移）
// - 工具条：放大/缩小、适应屏幕、实际大小、源码视图切换、下载 PNG/SVG、
//   复制源码、全屏
// - 解析失败时展示错误详情（mermaid.parse 预检捕获）并回退源码
//
// mermaid 仍走动态 import() 独立 chunk —— 不打开含图表的会话不加载该依赖，
// 主包体积零增长。

import {
  Check,
  Copy,
  Download,
  Edit3,
  Expand,
  FileDown,
  Maximize2,
  RotateCcw,
  X,
  ZoomIn,
  ZoomOut,
} from 'lucide-react';
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

import { ShikiCodeBlock } from './ShikiCodeBlock';

/** 本组件实际消费的 mermaid 最小接口（不耦合其类型导出方式） */
interface MermaidApi {
  initialize(config: Record<string, unknown>): void;
  render(id: string, code: string): Promise<{ svg: string }>;
  /** 解析预检 —— mermaid v11 提供；缺失时跳过预检直接渲染 */
  parse?(code: string): Promise<unknown>;
}

export interface MermaidDiagramProps {
  code: string;
  theme: 'default' | 'dark';
}

let mermaidPromise: Promise<MermaidApi> | null = null;

function loadMermaid(): Promise<MermaidApi> {
  mermaidPromise ??= import('mermaid').then((mod) => {
    const api = (mod.default ?? mod) as MermaidApi;
    api.initialize({
      startOnLoad: false,
      securityLevel: 'strict',
      maxTextSize: 50000,
      maxEdges: 500,
    });
    return api;
  });
  return mermaidPromise;
}

/** render id 全局自增（同页多图/重渲染不冲突） */
let renderSeq = 0;

const ZOOM_MIN = 0.4;
const ZOOM_MAX = 3;
const ZOOM_STEP = 1.25;

const clampZoom = (z: number) => Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z));

/** 读取 SVG 自身尺寸（viewBox 优先，回退 width/height 属性，再回退布局盒） */
function measureSvg(svgEl: Element | null): { w: number; h: number } | null {
  if (!svgEl) return null;
  const viewBox = (svgEl as SVGSVGElement).viewBox?.baseVal;
  const w = viewBox?.width || Number(svgEl.getAttribute('width')) || 0;
  const h = viewBox?.height || Number(svgEl.getAttribute('height')) || 0;
  if (w > 0 && h > 0) return { w, h };
  const rect = svgEl.getBoundingClientRect();
  if (rect.width > 0 && rect.height > 0) return { w: rect.width, h: rect.height };
  return null;
}

/** 将容器内的 mermaid SVG 导出为 PNG 下载（2x 分辨率，按主题铺底色） */
function downloadSvgAsPng(container: HTMLElement | null, theme: 'default' | 'dark'): void {
  const svgEl = container?.querySelector('svg');
  if (!svgEl) return;
  const xml = new XMLSerializer().serializeToString(svgEl);
  // btoa 只吃 latin1 —— 先 UTF-8 编码再逐字节转 latin1
  const svg64 = `data:image/svg+xml;base64,${btoa(unescape(encodeURIComponent(xml)))}`;
  const img = new Image();
  img.onload = () => {
    const scale = 2;
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, (img.width || 800) * scale);
    canvas.height = Math.max(1, (img.height || 600) * scale);
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.fillStyle = theme === 'dark' ? '#141519' : '#ffffff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    canvas.toBlob((blob) => {
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'mermaid-diagram.png';
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }, 'image/png');
  };
  img.src = svg64;
}

/** 审计快照输入 —— 与历史 MermaidBlock 契约保持一致（字段不可增删） */
export interface MermaidBlockAuditInput {
  state: 'loading' | 'ready' | 'failed';
  theme: 'dark' | 'default';
  zoomPct: number;
  fullscreen: boolean;
  codeLength: number;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatMermaidBlockAuditSnapshot(input: MermaidBlockAuditInput): string {
  return `state=${input.state}|theme=${input.theme}|zoom=${input.zoomPct}|fs=${input.fullscreen ? 1 : 0}|len=${input.codeLength}`;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatMermaidBlockAuditJson(input: MermaidBlockAuditInput): string {
  return JSON.stringify({
    state: input.state,
    theme: input.theme,
    zoomPct: input.zoomPct,
    fullscreen: input.fullscreen,
    codeLength: input.codeLength,
  });
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

export function MermaidDiagram({ code, theme }: MermaidDiagramProps) {
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [showSource, setShowSource] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [viewportEl, setViewportEl] = useState<HTMLDivElement | null>(null);
  const figureRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef({ active: false, x: 0, y: 0 });
  const copiedTimerRef = useRef<number | null>(null);

  // 卸载时清掉「已复制」回退定时器，避免卸载后 setState / 测试残留 timer
  useEffect(
    () => () => {
      if (copiedTimerRef.current !== null) window.clearTimeout(copiedTimerRef.current);
    },
    [],
  );

  useEffect(() => {
    let cancelled = false;
    const id = `sage-mermaid-${++renderSeq}`;
    setError(null);
    loadMermaid()
      .then(async (mermaid) => {
        // 每次渲染前按当前主题重设（dark/light 切换后新渲染即跟随）
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: 'strict',
          theme,
          maxTextSize: 50000,
          maxEdges: 500,
        });
        // 解析预检 —— 语法错误在此抛出，错误详情比 render 失败更具体
        if (typeof mermaid.parse === 'function') {
          await mermaid.parse(code);
        }
        const { svg: out } = await mermaid.render(id, code);
        if (cancelled) return;
        setSvg(out);
        setZoom(1);
        setPan({ x: 0, y: 0 });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [code, theme]);

  // ESC 关闭全屏
  useEffect(() => {
    if (!fullscreen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setFullscreen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [fullscreen]);

  // Ctrl+滚轮缩放 —— 原生非 passive 监听，才能拦掉浏览器自身的页面缩放
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

  const zoomBy = useCallback((factor: number) => {
    setZoom((z) => clampZoom(+(z * factor).toFixed(3)));
  }, []);

  /** 实际大小 —— 缩放归 100% 且清空位移 */
  const resetView = useCallback(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }, []);

  /** 适应屏幕 —— 按容器与 SVG 原始尺寸之比取缩放；尺寸不可用时退回实际大小 */
  const fitToScreen = useCallback(() => {
    const container = viewportEl;
    const size = measureSvg(figureRef.current?.querySelector('svg') ?? null);
    if (!container || !size || container.clientWidth <= 0 || container.clientHeight <= 0) {
      resetView();
      return;
    }
    const scale = Math.min(container.clientWidth / size.w, container.clientHeight / size.h);
    setZoom(clampZoom(+(scale.toFixed(3))));
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
        // 旧内核/jsdom 不支持指针捕获 —— 拖拽仍可用（事件在元素内冒泡）
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

  const copySource = useCallback(async () => {
    await navigator.clipboard?.writeText(code);
    setCopied(true);
    if (copiedTimerRef.current !== null) window.clearTimeout(copiedTimerRef.current);
    copiedTimerRef.current = window.setTimeout(() => setCopied(false), 1500);
  }, [code]);

  const exportPng = useCallback(() => downloadSvgAsPng(figureRef.current, theme), [theme]);

  const exportSvg = useCallback(() => {
    if (!svg) return;
    const blob = new Blob([svg], { type: 'image/svg+xml;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'mermaid-diagram.svg';
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }, [svg]);

  const state: MermaidBlockAuditInput['state'] = error
    ? 'failed'
    : svg === null
      ? 'loading'
      : 'ready';
  const auditInput: MermaidBlockAuditInput = {
    state,
    theme,
    zoomPct: Math.round(zoom * 100),
    fullscreen,
    codeLength: code.length,
  };
  const auditSnapshot = formatMermaidBlockAuditSnapshot(auditInput);
  const auditJson = formatMermaidBlockAuditJson(auditInput);

  const auditControls = (
    <span className="sr-only">
      <span
        role="status"
        tabIndex={0}
        data-testid="mermaid-block-audit-copy"
        data-mermaid-block-audit={auditSnapshot}
        aria-label="复制图表审计快照"
        onClick={() => {
          void navigator.clipboard?.writeText(auditSnapshot);
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            void navigator.clipboard?.writeText(auditSnapshot);
          }
        }}
      >
        快照
      </span>
      <span
        role="status"
        tabIndex={0}
        data-testid="mermaid-block-audit-copy-json"
        data-mermaid-block-audit-json={auditJson}
        aria-label="复制图表审计 JSON"
        onClick={() => {
          void navigator.clipboard?.writeText(auditJson);
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            void navigator.clipboard?.writeText(auditJson);
          }
        }}
      >
        JSON
      </span>
    </span>
  );

  if (error) {
    return (
      <div data-testid="mermaid-fallback" data-mermaid-block-audit={auditSnapshot}>
        {auditControls}
        <div className="text-xs text-amber-600 dark:text-amber-400 mb-1">
          Mermaid 图表渲染失败，显示源码
        </div>
        <div
          data-testid="mermaid-error-detail"
          className="text-xs text-amber-700 dark:text-amber-300 mb-2 whitespace-pre-wrap break-words"
        >
          {error}
        </div>
        <ShikiCodeBlock language="mermaid">{code}</ShikiCodeBlock>
      </div>
    );
  }

  if (svg === null) {
    // P23: 加载骨架屏（对齐 animate-shimmer 模式，替代纯文字）
    return (
      <div
        data-testid="mermaid-loading"
        data-mermaid-block-audit={auditSnapshot}
        className="my-2 p-4 rounded border border-border space-y-2"
      >
        {auditControls}
        <div className="h-3 w-1/3 rounded bg-bg-subtle animate-pulse" />
        <div className="h-24 rounded bg-bg-subtle animate-pulse" />
        <div className="text-xs text-muted text-center">渲染图表…</div>
      </div>
    );
  }

  const transform =
    pan.x === 0 && pan.y === 0
      ? `scale(${zoom})`
      : `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`;

  const figure = (
    <div
      ref={figureRef}
      data-testid="mermaid-figure"
      data-mermaid-block-audit={auditSnapshot}
      className="my-2 p-2 overflow-hidden rounded border border-border bg-white dark:bg-transparent [&_svg]:max-w-none"
    >
      <div
        data-testid="mermaid-canvas"
        style={{ transform, transformOrigin: 'top left' }}
        className="inline-block min-w-full"
        dangerouslySetInnerHTML={{ __html: svg }}
      />
    </div>
  );

  const viewport = (
    <div
      ref={setViewportEl}
      data-testid="mermaid-viewport"
      className="overflow-hidden cursor-grab active:cursor-grabbing select-none"
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerUp}
      onPointerLeave={handlePointerUp}
      onDoubleClick={resetView}
    >
      {figure}
    </div>
  );

  const sourceView = (
    <textarea
      data-testid="mermaid-source-textarea"
      aria-label="Mermaid 源码"
      readOnly
      value={code}
      className="w-full min-h-[12rem] p-2 font-mono text-xs bg-bg text-text border border-border rounded resize-y"
    />
  );

  const renderToolbar = (variant: 'hover' | 'bar') => (
    <div
      data-testid="mermaid-toolbar"
      className={
        variant === 'hover'
          ? 'absolute top-1 right-1 z-10 flex items-center gap-0.5 p-0.5 rounded bg-surface/95 border border-border shadow-sm opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity'
          : 'flex items-center gap-0.5 p-0.5 rounded bg-surface/95 border border-border'
      }
    >
      <ToolButton label="放大" onClick={() => zoomBy(ZOOM_STEP)} testid="mermaid-zoom-in">
        <ZoomIn className="w-3.5 h-3.5" />
      </ToolButton>
      <span
        data-testid="mermaid-zoom-label"
        className="text-ui-xs text-muted w-8 text-center tabular-nums"
      >
        {Math.round(zoom * 100)}%
      </span>
      <ToolButton label="缩小" onClick={() => zoomBy(1 / ZOOM_STEP)} testid="mermaid-zoom-out">
        <ZoomOut className="w-3.5 h-3.5" />
      </ToolButton>
      <ToolButton label="适应屏幕" onClick={fitToScreen} testid="mermaid-fit">
        <Maximize2 className="w-3.5 h-3.5" />
      </ToolButton>
      <ToolButton label="实际大小" onClick={resetView} testid="mermaid-actual-size">
        <RotateCcw className="w-3.5 h-3.5" />
      </ToolButton>
      <ToolButton
        label={showSource ? '显示图表' : '显示源码'}
        onClick={() => setShowSource((s) => !s)}
        testid="mermaid-toggle-source"
      >
        <Edit3 className="w-3.5 h-3.5" />
      </ToolButton>
      <ToolButton label="下载 PNG" onClick={exportPng} testid="mermaid-download-png">
        <Download className="w-3.5 h-3.5" />
      </ToolButton>
      <ToolButton label="下载 SVG" onClick={exportSvg} testid="mermaid-download-svg">
        <FileDown className="w-3.5 h-3.5" />
      </ToolButton>
      <ToolButton
        label={copied ? '已复制' : '复制源码'}
        onClick={() => void copySource()}
        testid="mermaid-copy-source"
      >
        {copied ? (
          <Check className="w-3.5 h-3.5 text-green-500" />
        ) : (
          <Copy className="w-3.5 h-3.5" />
        )}
      </ToolButton>
      {variant === 'hover' ? (
        <ToolButton
          label="全屏"
          onClick={() => setFullscreen(true)}
          testid="mermaid-fullscreen-open"
        >
          <Expand className="w-3.5 h-3.5" />
        </ToolButton>
      ) : (
        <ToolButton
          label="退出全屏"
          onClick={() => setFullscreen(false)}
          testid="mermaid-fullscreen-close"
        >
          <X className="w-3.5 h-3.5" />
        </ToolButton>
      )}
    </div>
  );

  if (fullscreen) {
    return createPortal(
      <div
        data-testid="mermaid-fullscreen"
        className="fixed inset-0 z-[70] bg-black/90 flex flex-col"
        onClick={(e) => {
          if (e.target === e.currentTarget) setFullscreen(false);
        }}
      >
        <div className="flex items-center justify-end gap-1 p-2">{renderToolbar('bar')}</div>
        <div className="flex-1 overflow-hidden">{showSource ? sourceView : viewport}</div>
      </div>,
      document.body,
    );
  }

  return (
    <div className="relative group">
      {/* mermaid SVG 自带配色：亮色 'default' 主题按白底设计 → 白底卡片；
          暗色 'dark' 主题按暗底设计（浅色线条 + 透明背景）→ 跟随应用暗色
          表面。此前恒为 bg-white，把 dark 配色的图钉在白底上导致对比度错乱。
          strict 模式下输出无脚本，dangerouslySetInnerHTML 安全。 */}
      {renderToolbar('hover')}
      {auditControls}
      {showSource ? sourceView : viewport}
    </div>
  );
}
