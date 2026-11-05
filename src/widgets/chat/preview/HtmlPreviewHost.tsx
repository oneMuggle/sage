// src/widgets/chat/preview/HtmlPreviewHost.tsx
//
// HTML 预览统一宿主（feat/rich-preview-rendering）。
//
// 三处 HTML 预览入口此前各写一个裸 iframe：没有工具条、没有错误反馈、
// 不能重跑也不能停止。本组件把三处收敛到同一实现：
//   - 工具条：重新执行 / 停止 / 全屏 / 复制源码 / 下载
//   - 错误桥：预览页里的 error / unhandledrejection / console.error 回传横幅
//   - 独立源：桌面端走 sage-preview://（预览文档不受渲染层 CSP 约束，
//     用户的内联脚本与 CDN 脚本在打包版也能运行）；Web / 测试环境退回 srcDoc。
//
// 安全边界：iframe 恒为 `sandbox="allow-scripts"`（无 allow-same-origin），
// 预览文档运行在 opaque origin，拿不到应用 cookie / storage / DOM。
import {
  AlertTriangle,
  Copy,
  Download,
  Maximize2,
  Minimize2,
  RotateCw,
  Square,
  X,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import { PREVIEW_BRIDGE_CHANNEL, injectPreviewBridge } from '../../../shared/lib/htmlPreviewBridge';

export interface HtmlPreviewIssue {
  kind: string;
  message: string;
  detail: string;
}

export interface HtmlPreviewHostProps {
  /** 预览的 HTML 原文 —— 用户看到的源码，复制/下载都用它（不含桥接脚本） */
  html: string;
  /** 文件名 —— 下载时的默认文件名，同时作为 iframe title */
  name: string;
  /** 外部刷新计数：变化即重挂载并重跑脚本 */
  reloadKey?: number;
  /** iframe 的 data-testid */
  frameTestId?: string;
  /** 外层容器类名 */
  className?: string;
  /** 预览区高度类名（默认 h-96） */
  heightClassName?: string;
}

/** 最多保留的诊断条数 —— 防止死循环脚本刷爆内存。 */
const MAX_ISSUES = 20;

function downloadFileName(name: string): string {
  const base = name.split(/[\\/]/).pop()?.trim() || 'preview.html';
  return /\.html?$/i.test(base) ? base : `${base}.html`;
}

export function HtmlPreviewHost({
  html,
  name,
  reloadKey = 0,
  frameTestId = 'html-preview-frame',
  className,
  heightClassName = 'h-96',
}: HtmlPreviewHostProps) {
  const [runEpoch, setRunEpoch] = useState(0);
  const [stopped, setStopped] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [issues, setIssues] = useState<HtmlPreviewIssue[]>([]);
  const [protocolUrl, setProtocolUrl] = useState<string | null>(null);
  const frameRef = useRef<HTMLIFrameElement | null>(null);

  // 桌面端 preload 注入了 preview 桥 → 走独立源；Web / 测试环境没有 → srcDoc。
  const [hasProtocol] = useState(
    () => typeof window !== 'undefined' && Boolean(window.electronAPI?.preview),
  );
  const renderedHtml = useMemo(() => injectPreviewBridge(html), [html]);

  // 发布到主进程 → 换取 sage-preview:// URL。停止时不发布；恢复时重发。
  useEffect(() => {
    if (!hasProtocol || stopped) return;
    const api = window.electronAPI?.preview;
    if (!api) return;
    let cancelled = false;
    let publishedId: string | null = null;
    setProtocolUrl(null);
    void api
      .publish(renderedHtml)
      .then((res) => {
        if (cancelled) {
          void api.revoke(res.id);
          return;
        }
        publishedId = res.id;
        setProtocolUrl(res.url);
      })
      .catch(() => setProtocolUrl(null));
    return () => {
      cancelled = true;
      if (publishedId) void api.revoke(publishedId);
    };
  }, [hasProtocol, renderedHtml, reloadKey, runEpoch, stopped]);

  // 错误桥：只接受来自本预览 iframe 的、通道名匹配的消息。
  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.source !== frameRef.current?.contentWindow) return;
      const data = event.data as (Partial<HtmlPreviewIssue> & { channel?: string }) | null;
      if (!data || data.channel !== PREVIEW_BRIDGE_CHANNEL) return;
      setIssues((prev) => {
        const next = [
          ...prev,
          {
            kind: typeof data.kind === 'string' ? data.kind : 'error',
            message: typeof data.message === 'string' ? data.message : '未知错误',
            detail: typeof data.detail === 'string' ? data.detail : '',
          },
        ];
        return next.length > MAX_ISSUES ? next.slice(next.length - MAX_ISSUES) : next;
      });
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, []);

  const handleRerun = useCallback(() => {
    setStopped(false);
    setIssues([]);
    setRunEpoch((n) => n + 1);
  }, []);

  const handleStop = useCallback(() => {
    setStopped(true);
  }, []);

  const handleCopy = useCallback(() => {
    void navigator.clipboard?.writeText(html)?.catch(() => {});
  }, [html]);

  const handleDownload = useCallback(() => {
    try {
      const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = downloadFileName(name);
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch {
      // 环境不支持 createObjectURL（如部分测试运行时）—— 静默跳过下载。
    }
  }, [html, name]);

  const frameKey = `${reloadKey}-${runEpoch}-${protocolUrl ?? 'inline'}`;

  const toolbar = (
    <div className="flex items-center gap-0.5 px-1.5 py-1 border-b border-border bg-bg-subtle">
      <button
        type="button"
        className="p-1 rounded hover:bg-bg-hover text-text-secondary hover:text-text transition-colors"
        title="重新执行"
        aria-label="重新执行"
        data-testid="html-preview-rerun"
        onClick={handleRerun}
      >
        <RotateCw className="w-3.5 h-3.5" />
      </button>
      <button
        type="button"
        className="p-1 rounded hover:bg-bg-hover text-text-secondary hover:text-text transition-colors disabled:opacity-40"
        title="停止"
        aria-label="停止"
        data-testid="html-preview-stop"
        disabled={stopped}
        onClick={handleStop}
      >
        <Square className="w-3.5 h-3.5" />
      </button>
      <button
        type="button"
        className="p-1 rounded hover:bg-bg-hover text-text-secondary hover:text-text transition-colors"
        title={fullscreen ? '退出全屏' : '全屏'}
        aria-label={fullscreen ? '退出全屏' : '全屏'}
        data-testid="html-preview-fullscreen-toggle"
        onClick={() => setFullscreen((v) => !v)}
      >
        {fullscreen ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
      </button>
      <button
        type="button"
        className="p-1 rounded hover:bg-bg-hover text-text-secondary hover:text-text transition-colors"
        title="复制源码"
        aria-label="复制源码"
        data-testid="html-preview-copy"
        onClick={handleCopy}
      >
        <Copy className="w-3.5 h-3.5" />
      </button>
      <button
        type="button"
        className="p-1 rounded hover:bg-bg-hover text-text-secondary hover:text-text transition-colors"
        title="下载 HTML"
        aria-label="下载 HTML"
        data-testid="html-preview-download"
        onClick={handleDownload}
      >
        <Download className="w-3.5 h-3.5" />
      </button>
      <span className="ml-auto text-xs text-muted truncate pl-2" title={name}>
        {name}
      </span>
    </div>
  );

  const errorBanner =
    issues.length > 0 ? (
      <div
        className="flex items-start gap-1.5 px-2 py-1.5 border-b border-border bg-error/10 text-error text-xs"
        data-testid="html-preview-errors"
      >
        <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="break-words">{issues[0]?.message}</div>
          {issues.length > 1 && (
            <div className="text-muted mt-0.5">另有 {issues.length - 1} 条诊断</div>
          )}
        </div>
        <button
          type="button"
          className="p-0.5 rounded hover:bg-bg-hover"
          title="清除诊断"
          aria-label="清除诊断"
          data-testid="html-preview-errors-clear"
          onClick={() => setIssues([])}
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
    ) : null;

  const frame = stopped ? (
    <div
      className={`w-full ${heightClassName} flex items-center justify-center text-xs text-muted bg-bg-subtle`}
      data-testid="html-preview-stopped"
    >
      预览已停止
    </div>
  ) : (
    <iframe
      key={frameKey}
      ref={frameRef}
      src={protocolUrl ?? undefined}
      srcDoc={protocolUrl ? undefined : renderedHtml}
      sandbox="allow-scripts"
      referrerPolicy="no-referrer"
      title={name}
      className={`w-full ${heightClassName} bg-white border-0`}
      data-testid={frameTestId}
    />
  );

  const panel = (
    <div
      className={`flex flex-col overflow-hidden ${className ?? ''}`}
      data-testid="html-preview-host"
      style={fullscreen ? { height: '100%' } : undefined}
    >
      {toolbar}
      {errorBanner}
      {frame}
    </div>
  );

  if (fullscreen) {
    return createPortal(
      <div
        className="fixed inset-0 z-[9999] bg-bg flex flex-col"
        data-testid="html-preview-fullscreen"
      >
        {panel}
      </div>,
      document.body,
    );
  }
  return panel;
}
