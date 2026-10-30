// src/widgets/chat/artifacts/ArtifactViewer.tsx
import {
  ArrowLeft,
  Copy,
  Eye,
  FileCode,
  FolderOpen,
  Pencil,
  RefreshCw,
  Save,
  X,
} from 'lucide-react';
import { lazy, Suspense, useCallback, useEffect, useState } from 'react';

import type { Artifact, ArtifactKind } from '../../../features/artifacts/artifactApi';
import { revealArtifact, updateArtifactContent } from '../../../features/artifacts/artifactApi';
import { useArtifactContent } from '../../../features/artifacts/useArtifactContent';
import { FileContentRenderer } from '../preview/FileContentRenderer';

import { VersionHistory } from './VersionHistory';

// 2026-09-23 perf: CodeMirror（@uiw/react-codemirror + @codemirror/*，约
// 400KB min）此前被 RightPanel → ArtifactViewer 的 eager 引用链拖进 index
// 主 chunk（1.5MB）。编辑器只在「代码产物点编辑」时才需要——改 lazy 切片，
// chunk 落在首次进入编辑态时从本地磁盘加载（file:// 近即时）。fallback 用
// 同字体的只读 pre 承接，加载期内容不闪空。
const CodeMirrorEditor = lazy(() => import('@uiw/react-codemirror'));

interface ArtifactViewerProps {
  artifact: Artifact;
  sessionId: string;
  onBack: () => void;
}

/** Kinds eligible for the text edit panel. */
const EDITABLE_KINDS: ReadonlySet<ArtifactKind> = new Set([
  'markdown',
  'code',
  'json',
  'text',
  'csv',
]);

// right-panel R2 批次 A: markdown 渲染 / CSV 表格 / 各类型内容分发已上移至
// shared 预览组件 FileContentRenderer（消息内文件预览共用，feat/file-reference-preview）

export function ArtifactViewer({ artifact, sessionId, onBack }: ArtifactViewerProps) {
  const { content, loading, refresh } = useArtifactContent(sessionId, artifact.id);
  // R3 批次 B: 跟随应用主题（ThemeProvider 同步维护 .dark class，直读
  // 避免 hook 依赖；主题切换在编辑态挂载后的场景极罕见，不订阅）
  const themeResolved: 'light' | 'dark' = document.documentElement.classList.contains('dark')
    ? 'dark'
    : 'light';
  const [editMode, setEditMode] = useState(false);
  const [editContent, setEditContent] = useState('');
  const [editBaseHash, setEditBaseHash] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  // right-panel R2 批次 A: markdown 渲染/源码切换（默认渲染）+ HTML 预览刷新
  const [mdRendered, setMdRendered] = useState(true);
  const [htmlReloadKey, setHtmlReloadKey] = useState(0);
  // 2026-10-29: docx 默认 Word 版式（docx-preview）；渲染失败或用户切换时
  // 回退到结构化段落视图。
  const [docxFidelity, setDocxFidelity] = useState(true);
  const [docxFidelityFailed, setDocxFidelityFailed] = useState(false);

  useEffect(() => {
    setDocxFidelity(true);
    setDocxFidelityFailed(false);
  }, [artifact.id]);

  const isEditable =
    content?.ok && content.kind && EDITABLE_KINDS.has(content.kind as ArtifactKind);

  const enterEditMode = useCallback(async () => {
    if (!content?.ok || !content.content) return;
    setEditContent(content.content);
    // Compute SHA-256 hash of current content for optimistic concurrency
    try {
      const encoder = new TextEncoder();
      const data = encoder.encode(content.content);
      const hashBuffer = await crypto.subtle.digest('SHA-256', data);
      const hashArray = Array.from(new Uint8Array(hashBuffer));
      const hashHex = hashArray.map((b) => b.toString(16).padStart(2, '0')).join('');
      setEditBaseHash(hashHex);
    } catch {
      setEditBaseHash('');
    }
    setEditMode(true);
    setSaveError(null);
  }, [content]);

  const handleSave = async () => {
    if (!editBaseHash) {
      setSaveError('无法保存：缺少内容哈希，请刷新后重试');
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      await updateArtifactContent(sessionId, artifact.id, editBaseHash, editContent, 'edit');
      setEditMode(false);
      await refresh();
    } catch (e: unknown) {
      setSaveError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-2 py-1 border-b border-border">
        <button className="p-1.5 rounded hover:bg-bg-hover" onClick={onBack} aria-label="返回">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div className="flex-1 min-w-0 text-sm">
          <span className="text-muted">产物</span>
          <span className="mx-1 text-muted">/</span>
          <span className="text-text">{artifact.name}</span>
        </div>
        {/* right-panel R2 批次 A: markdown 渲染/源码切换 + HTML 预览刷新 */}
        {content?.ok && content.kind === 'markdown' && !editMode && (
          <button
            className="p-1.5 rounded hover:bg-bg-hover text-text-secondary hover:text-text transition-colors"
            title={mdRendered ? '查看源码' : '渲染预览'}
            aria-label={mdRendered ? '查看源码' : '渲染预览'}
            data-testid="artifact-md-toggle"
            onClick={() => setMdRendered((v) => !v)}
          >
            {mdRendered ? <FileCode className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
          </button>
        )}
        {content?.ok && content.kind === 'html' && (
          <button
            className="p-1.5 rounded hover:bg-bg-hover text-text-secondary hover:text-text transition-colors"
            title="刷新预览"
            aria-label="刷新预览"
            data-testid="artifact-html-refresh"
            onClick={() => setHtmlReloadKey((k) => k + 1)}
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        )}
        {content?.ok && content.kind === 'docx' && content.data_url && (
          <button
            className="p-1.5 rounded hover:bg-bg-hover text-text-secondary hover:text-text transition-colors"
            title={docxFidelity && !docxFidelityFailed ? '切换为文本视图' : '切换为 Word 版式'}
            aria-label={docxFidelity && !docxFidelityFailed ? '切换为文本视图' : '切换为 Word 版式'}
            data-testid="artifact-docx-view-toggle"
            onClick={() => {
              // 失败态下点击 = 重试 Word 版式；正常态下在两种视图间切换
              if (docxFidelityFailed) {
                setDocxFidelityFailed(false);
                setDocxFidelity(true);
                return;
              }
              setDocxFidelity((v) => !v);
            }}
          >
            {docxFidelity && !docxFidelityFailed ? (
              <FileCode className="w-4 h-4" />
            ) : (
              <Eye className="w-4 h-4" />
            )}
          </button>
        )}
        {isEditable && !editMode && (
          <button className="p-1.5 rounded hover:bg-bg-hover" title="编辑" onClick={enterEditMode}>
            <Pencil className="w-4 h-4" />
          </button>
        )}
        {editMode && (
          <>
            <button
              className="p-1.5 rounded hover:bg-bg-hover text-text-secondary disabled:opacity-50"
              title="保存"
              disabled={saving}
              onClick={() => void handleSave()}
            >
              <Save className="w-4 h-4" />
            </button>
            <button
              className="p-1.5 rounded hover:bg-bg-hover"
              title="取消编辑"
              onClick={() => {
                setEditMode(false);
                setSaveError(null);
              }}
            >
              <X className="w-4 h-4" />
            </button>
          </>
        )}
        <button
          className="p-1.5 rounded hover:bg-bg-hover"
          title="复制路径"
          onClick={() => {
            void navigator.clipboard?.writeText(artifact.path)?.catch(() => {});
          }}
        >
          <Copy className="w-4 h-4" />
        </button>
        <button
          className="p-1.5 rounded hover:bg-bg-hover"
          title="在文件管理器中显示"
          onClick={() => {
            revealArtifact(sessionId, artifact.id).catch(() => {});
          }}
        >
          <FolderOpen className="w-4 h-4" />
        </button>
      </div>

      <div className="flex-1 overflow-auto p-3">
        {editMode ? (
          <div className="flex flex-col h-full" data-testid="artifact-edit-codemirror">
            {/* R3 批次 B: textarea → CodeMirror（行号 + 语法高亮编辑），
                value/onChange 与乐观并发 hash 保存逻辑完全兼容 */}
            <div className="flex-1 min-h-0 border border-border rounded overflow-auto bg-bg-input">
              <Suspense
                fallback={
                  <pre className="h-full overflow-auto bg-bg-input p-3 text-code font-mono leading-relaxed">
                    {editContent}
                  </pre>
                }
              >
                <CodeMirrorEditor
                  value={editContent}
                  height="100%"
                  theme={themeResolved}
                  basicSetup={{ lineNumbers: true, foldGutter: false, highlightActiveLine: true }}
                  onChange={(value) => setEditContent(value)}
                />
              </Suspense>
            </div>
            {saveError && <div className="mt-2 text-xs text-error">{saveError}</div>}
          </div>
        ) : loading ? (
          <div className="text-sm text-muted">加载中...</div>
        ) : content ? (
          <FileContentRenderer
            content={content}
            name={artifact.name}
            mdRendered={mdRendered}
            htmlReloadKey={htmlReloadKey}
            docxFidelity={docxFidelity && !docxFidelityFailed}
            onDocxFidelityError={() => setDocxFidelityFailed(true)}
          />
        ) : (
          <div className="text-sm text-error">加载失败</div>
        )}
      </div>

      <VersionHistory
        sessionId={sessionId}
        artifactId={artifact.id}
        onRestoreComplete={() => void refresh()}
      />
    </div>
  );
}

export interface ArtifactViewerAuditInput {
  artifactId: string;
  artifactType: string;
  contentByteLength: number;
  sandboxEnabled: boolean;
}

export interface ArtifactViewerAuditReport {
  artifactId: string;
  normalizedType: string;
  contentByteLength: number;
  sandboxEnabled: boolean;
  healthy: boolean;
  issueCodes: string[];
}

// eslint-disable-next-line react-refresh/only-export-components
export function evaluateArtifactViewerAudit(
  input: ArtifactViewerAuditInput,
): ArtifactViewerAuditReport {
  const artifactId = input.artifactId.trim();
  const normalizedType = input.artifactType.trim().toLowerCase() || 'unknown';
  const contentByteLength = Math.max(0, Math.trunc(input.contentByteLength));
  const sandboxEnabled = Boolean(input.sandboxEnabled);
  const issueCodes: string[] = [];

  if (!artifactId) {
    issueCodes.push('missing_artifact_id');
  }
  if (contentByteLength === 0) {
    issueCodes.push('empty_artifact_content');
  }
  if ((normalizedType === 'html' || normalizedType === 'svg') && !sandboxEnabled) {
    issueCodes.push('unsandboxed_rich_artifact');
  }

  return {
    artifactId,
    normalizedType,
    contentByteLength,
    sandboxEnabled,
    healthy: issueCodes.length === 0,
    issueCodes,
  };
}

// eslint-disable-next-line react-refresh/only-export-components
export function exportArtifactViewerAuditJson(input: ArtifactViewerAuditInput): string {
  return JSON.stringify(evaluateArtifactViewerAudit(input));
}
