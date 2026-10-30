// src/widgets/chat/preview/FilePreviewPanel.tsx
//
// 消息内文件引用 → 右栏统一预览（feat/file-reference-preview）。
// 数据源：GET /sessions/{id}/workspace/preview（工作区边界由后端校验）。
// 内容渲染复用 FileContentRenderer，与产物预览同一套分发。
import { ArrowLeft, ClipboardCopy, ExternalLink, RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';

import { workspaceApi } from '../../../shared/api/workspaceApi';

import { FileContentRenderer, type PreviewContentPayload } from './FileContentRenderer';

interface FilePreviewPanelProps {
  sessionId: string;
  /** 工作区相对路径或工作区内绝对路径 */
  path: string;
  onBack: () => void;
}

function fileNameOf(path: string): string {
  const normalized = path.replace(/\\/g, '/');
  const idx = normalized.lastIndexOf('/');
  return idx >= 0 ? normalized.slice(idx + 1) : normalized;
}

export function FilePreviewPanel({ sessionId, path, onBack }: FilePreviewPanelProps) {
  const [content, setContent] = useState<PreviewContentPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestSeq = useRef(0);

  const load = useCallback(async () => {
    const seq = ++requestSeq.current;
    setLoading(true);
    setError(null);
    try {
      const result = await workspaceApi.previewFile(sessionId, path);
      if (requestSeq.current !== seq) return;
      setContent(result);
    } catch (err: unknown) {
      if (requestSeq.current !== seq) return;
      setContent(null);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (requestSeq.current === seq) setLoading(false);
    }
  }, [sessionId, path]);

  useEffect(() => {
    void load();
    return () => {
      // 失效在途请求（切换文件时旧响应不再落状态）
      requestSeq.current += 1;
    };
  }, [load]);

  const name = fileNameOf(path);
  const canOpenInEditor = Boolean(window.electronAPI?.file?.openInEditor);

  return (
    <div className="flex flex-col h-full" data-testid="file-preview-panel">
      <div className="flex items-center gap-2 px-2 py-1 border-b border-border">
        <button
          className="p-1.5 rounded hover:bg-bg-hover"
          onClick={onBack}
          aria-label="返回"
          data-testid="file-preview-back"
        >
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div className="flex-1 min-w-0 text-sm" title={path}>
          <span className="text-muted">文件</span>
          <span className="mx-1 text-muted">/</span>
          <span className="text-text truncate">{name}</span>
        </div>
        <button
          className="p-1.5 rounded hover:bg-bg-hover text-text-secondary hover:text-text transition-colors"
          title="刷新"
          aria-label="刷新"
          onClick={() => void load()}
        >
          <RefreshCw className={'w-4 h-4' + (loading ? ' animate-spin' : '')} />
        </button>
        <button
          className="p-1.5 rounded hover:bg-bg-hover"
          title="复制路径"
          onClick={() => {
            void navigator.clipboard?.writeText(path)?.catch(() => {});
          }}
        >
          <ClipboardCopy className="w-4 h-4" />
        </button>
        {canOpenInEditor && (
          <button
            className="p-1.5 rounded hover:bg-bg-hover"
            title="在编辑器中打开"
            onClick={() => {
              void window.electronAPI?.file?.openInEditor?.(sessionId, path).catch(() => {});
            }}
          >
            <ExternalLink className="w-4 h-4" />
          </button>
        )}
      </div>

      <div className="flex-1 overflow-auto p-3">
        {loading && !content ? (
          <div className="text-sm text-muted">加载中...</div>
        ) : error ? (
          <div className="text-sm text-error" data-testid="file-preview-error">
            {error}
          </div>
        ) : content ? (
          <>
            <FileContentRenderer content={content} name={name} />
            {content.truncated && (
              <div className="mt-2 text-xs text-muted">内容过长，已截断显示</div>
            )}
          </>
        ) : (
          <div className="text-sm text-muted">无可预览内容</div>
        )}
      </div>
    </div>
  );
}
