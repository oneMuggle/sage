// src/widgets/chat/MermaidBlock.tsx
//
// U7' (对标增强第五轮批次 A, docs/plans/2026-09-08_coding-agent-parity-round5.md):
// ```mermaid 代码块渲染为 SVG 图表。mermaid 经动态 import() 独立 chunk，
// 不打开含图表的会话不加载，主包体积零增长（round4 批次 F 评审结论见 §5）。
//
// 设计:
// - 模块级单例加载 mermaid（initialize 基线配置一次，render 前按当前主题重设）；
// - 主题跟随 ThemeProvider（html.dark → 'dark'，否则 'default'）；
// - 渲染失败（语法错误/超大图）回退 ShikiCodeBlock 源码展示，不静默吞错。
// - P1 (UI 优化方案 2026-09-13): 图表工具栏 —— 缩放/重置/全屏/下载 PNG/
//   复制源码（对标 Typora / mermaid.live）；缩放用 CSS transform，
//   不引第三方平移缩放库。

import { Check, Copy, Download, Maximize2, RotateCcw, X, ZoomIn, ZoomOut } from 'lucide-react';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

import { ShikiCodeBlock } from './ShikiCodeBlock';

/** 本组件实际消费的 mermaid 最小接口（不耦合其类型导出方式） */
interface MermaidApi {
  initialize(config: Record<string, unknown>): void;
  render(id: string, code: string): Promise<{ svg: string }>;
}

let mermaidPromise: Promise<MermaidApi> | null = null;

function currentTheme(): 'dark' | 'default' {
  return document.documentElement.classList.contains('dark') ? 'dark' : 'default';
}

async function loadMermaid(): Promise<MermaidApi> {
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

/** 将容器内的 mermaid SVG 导出为 PNG 下载（2x 分辨率，按主题铺底色） */
function downloadSvgAsPng(container: HTMLElement | null): void {
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
    ctx.fillStyle = currentTheme() === 'dark' ? '#141519' : '#ffffff';
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

export function MermaidBlock({ code }: { code: string }) {
  const [svg, setSvg] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  // 2026-09-13 P0: 主题响应式 — 此前 effect 依赖只有 [code]，会话中途切换
  // 亮/暗主题时图表不跟随（下次 code 变化才重渲染）。观察 html class 变化
  // (ThemeProvider 双轨切 .dark + data-theme) 触发重渲染。
  const [theme, setTheme] = useState<'dark' | 'default'>(currentTheme);
  // P1: 图表工具栏状态
  const [zoom, setZoom] = useState(1);
  const [fullscreen, setFullscreen] = useState(false);
  const [copied, setCopied] = useState(false);
  const figureRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const observer = new MutationObserver(() => setTheme(currentTheme()));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    let cancelled = false;
    const id = `sage-mermaid-${++renderSeq}`;
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
        const { svg: out } = await mermaid.render(id, code);
        if (cancelled) return;
        setSvg(out);
        setFailed(false);
        setZoom(1);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
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

  const zoomBy = (factor: number) => setZoom((z) => clampZoom(+(z * factor).toFixed(3)));

  const copySource = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const exportPng = () => downloadSvgAsPng(figureRef.current);

  if (failed) {
    return (
      <div data-testid="mermaid-fallback">
        <div className="text-xs text-amber-600 dark:text-amber-400 mb-1">
          Mermaid 图表渲染失败，显示源码
        </div>
        <ShikiCodeBlock language="mermaid">{code}</ShikiCodeBlock>
      </div>
    );
  }
  if (svg === null) {
    // P23: 加载骨架屏（对齐 animate-shimmer 模式，替代纯文字）
    return (
      <div data-testid="mermaid-loading" className="my-2 p-4 rounded border border-border space-y-2">
        <div className="h-3 w-1/3 rounded bg-bg-subtle animate-pulse" />
        <div className="h-24 rounded bg-bg-subtle animate-pulse" />
        <div className="text-xs text-muted text-center">渲染图表…</div>
      </div>
    );
  }

  const toolbar = (
    <div
      data-testid="mermaid-toolbar"
      className="absolute top-1 right-1 z-10 flex items-center gap-0.5 p-0.5 rounded bg-surface/95 border border-border shadow-sm opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity"
    >
      <ToolButton label="缩小" onClick={() => zoomBy(1 / ZOOM_STEP)}>
        <ZoomOut className="w-3.5 h-3.5" />
      </ToolButton>
      <span className="text-[10px] text-muted w-8 text-center tabular-nums">
        {Math.round(zoom * 100)}%
      </span>
      <ToolButton label="放大" onClick={() => zoomBy(ZOOM_STEP)}>
        <ZoomIn className="w-3.5 h-3.5" />
      </ToolButton>
      <ToolButton label="重置缩放" onClick={() => setZoom(1)}>
        <RotateCcw className="w-3.5 h-3.5" />
      </ToolButton>
      <ToolButton label="下载 PNG" onClick={exportPng}>
        <Download className="w-3.5 h-3.5" />
      </ToolButton>
      <ToolButton label={copied ? '已复制' : '复制源码'} onClick={copySource}>
        {copied ? <Check className="w-3.5 h-3.5 text-green-500" /> : <Copy className="w-3.5 h-3.5" />}
      </ToolButton>
      <ToolButton label="全屏" onClick={() => setFullscreen(true)} testid="mermaid-fullscreen-open">
        <Maximize2 className="w-3.5 h-3.5" />
      </ToolButton>
    </div>
  );

  return (
    <>
      {/* mermaid SVG 自带配色：亮色 'default' 主题按白底设计 → 白底卡片；
          暗色 'dark' 主题按暗底设计（浅色线条 + 透明背景）→ 跟随应用暗色
          表面。此前恒为 bg-white，把 dark 配色的图钉在白底上导致对比度错乱。
          strict 模式下输出无脚本，dangerouslySetInnerHTML 安全。 */}
      <div className="relative group">
        {toolbar}
        <div
          ref={figureRef}
          data-testid="mermaid-figure"
          className="my-2 p-2 overflow-auto rounded border border-border bg-white dark:bg-transparent [&_svg]:max-w-none"
        >
          <div
            style={{ transform: `scale(${zoom})`, transformOrigin: 'top left' }}
            className="inline-block min-w-full"
            dangerouslySetInnerHTML={{ __html: svg }}
          />
        </div>
      </div>

      {/* 全屏查看 — portal 到 body，ESC/点背景/× 关闭，共享 zoom 状态 */}
      {fullscreen &&
        createPortal(
          <div
            data-testid="mermaid-fullscreen"
            className="fixed inset-0 z-[70] bg-black/90 flex flex-col"
            onClick={(e) => {
              if (e.target === e.currentTarget) setFullscreen(false);
            }}
          >
            <div className="flex items-center justify-end gap-1 p-2">
              <ToolButton label="缩小" onClick={() => zoomBy(1 / ZOOM_STEP)}>
                <ZoomOut className="w-4 h-4 text-gray-300" />
              </ToolButton>
              <span className="text-xs text-gray-400 w-10 text-center tabular-nums">
                {Math.round(zoom * 100)}%
              </span>
              <ToolButton label="放大" onClick={() => zoomBy(ZOOM_STEP)}>
                <ZoomIn className="w-4 h-4 text-gray-300" />
              </ToolButton>
              <ToolButton label="重置缩放" onClick={() => setZoom(1)}>
                <RotateCcw className="w-4 h-4 text-gray-300" />
              </ToolButton>
              <ToolButton label="下载 PNG" onClick={exportPng}>
                <Download className="w-4 h-4 text-gray-300" />
              </ToolButton>
              <ToolButton label="退出全屏" onClick={() => setFullscreen(false)}>
                <X className="w-4 h-4 text-gray-300" />
              </ToolButton>
            </div>
            <div className="flex-1 overflow-auto flex items-start justify-center p-6">
              <div
                style={{ transform: `scale(${zoom})`, transformOrigin: 'top center' }}
                className="inline-block bg-white dark:bg-transparent rounded p-4"
                dangerouslySetInnerHTML={{ __html: svg }}
              />
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}
