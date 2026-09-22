// src/widgets/chat/artifacts/ArtifactViewer.tsx
import {
  ArrowLeft,
  ClipboardCopy,
  Copy,
  Eye,
  FileCode,
  FolderOpen,
  Pencil,
  RefreshCw,
  Save,
  X,
} from 'lucide-react';
import { lazy, Suspense, useCallback, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeKatex from 'rehype-katex';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';

import type { Artifact, ArtifactKind } from '../../../features/artifacts/artifactApi';
import { revealArtifact, updateArtifactContent } from '../../../features/artifacts/artifactApi';
import { useArtifactContent } from '../../../features/artifacts/useArtifactContent';
// Round B P3（统一预览组件）: chat 端 office 产物复用 Office 页的结构化
// 预览组件——公式视图/表头样式/渲染上限全部继承，两端视觉同源。
// 后端 read_office 现在随 html 一起返回 structured（read_* 的 JSON 序列
// 化）；缺失时回退旧的受控 HTML 路径。
import { ExcelPreview, PptPreview, WordPreview } from '../../../features/office';
import type {
  OfficeExcelReadResult,
  OfficePptReadResult,
  OfficeWordReadResult,
} from '../../../shared/api/types';
import { langFromPath } from '../../../shared/lib/fileLang';
import { ShikiCodeBlock } from '../ShikiCodeBlock';

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

// right-panel R2 批次 A: 常用扩展名 → Shiki 语言（未识别回落纯文本 pre）
// R6: 映射表上抬至 shared/lib/fileLang（变更面板预览共用），此处仅引用
function langFromName(name: string): string | undefined {
  return langFromPath(name);
}

/** R2 批次 A: markdown 产物渲染视图 —— 与消息流同口径（gfm + math + Shiki 代码块） */
const MD_REMARK = [remarkGfm, remarkMath];

function MarkdownRendered({ text }: { text: string }) {
  return (
    <div className="text-sm leading-relaxed" data-testid="artifact-md-rendered">
      <ReactMarkdown
        remarkPlugins={MD_REMARK}
        rehypePlugins={[rehypeKatex]}
        components={{
          code({ className, children }) {
            const match = /language-(\w+)/.exec(className || '');
            const content = String(children).replace(/\n$/, '');
            if (!match && !content.includes('\n')) {
              return (
                <code className="px-1.5 py-0.5 bg-bg-subtle rounded text-code font-mono">
                  {content}
                </code>
              );
            }
            return <ShikiCodeBlock language={match?.[1]}>{content}</ShikiCodeBlock>;
          },
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = '';
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          cell += '"';
          i++;
        } else quoted = false;
      } else cell += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ',') {
      row.push(cell);
      cell = '';
    } else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && text[i + 1] === '\n') i++;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = '';
    } else cell += ch;
  }
  if (cell !== '' || row.length) {
    row.push(cell);
    rows.push(row);
  }
  return rows.filter((r) => r.some((c) => c !== ''));
}

function CsvPreview({ text }: { text: string }) {
  const rows = parseCsv(text);
  const [copied, setCopied] = useState(false);
  if (rows.length === 0) return <div className="text-sm text-muted">空文件</div>;
  const [head, ...body] = rows;
  return (
    <div className="overflow-auto">
      <div className="flex justify-end mb-1">
        <button
          className="inline-flex items-center gap-1 px-1.5 py-0.5 text-xs text-text-secondary hover:text-text hover:bg-bg-hover rounded transition-colors"
          title="复制 CSV 全文"
          aria-label="复制 CSV 全文"
          data-testid="artifact-csv-copy"
          onClick={() => {
            void navigator.clipboard?.writeText(text)?.catch(() => {});
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          }}
        >
          <ClipboardCopy className="w-3.5 h-3.5" />
          {copied ? '已复制' : '复制全文'}
        </button>
      </div>
      <table className="text-xs border-collapse">
        <thead>
          <tr>
            {head.map((c, i) => (
              <th key={i} className="border px-2 py-1 bg-bg-hover">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.slice(0, 500).map((r, i) => (
            <tr key={i}>
              {r.map((c, j) => (
                <td key={j} className="border px-2 py-1">
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {body.length > 500 && <div className="text-xs text-muted mt-2">仅显示前 500 行</div>}
    </div>
  );
}

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
        ) : !content || !content.ok ? (
          <div className="text-sm text-error">{content?.error ?? '加载失败'}</div>
        ) : content.kind === 'image' ? (
          <img src={content.data_url} alt={artifact.name} className="max-w-full" />
        ) : content.kind === 'pdf' ? (
          // F11 (round4 批次 D): Chromium 内置 PDF viewer 内嵌渲染,零依赖
          <iframe
            src={content.data_url}
            title={artifact.name}
            className="w-full h-full min-h-[24rem] rounded border border-border"
          />
        ) : content.kind === 'html' ? (
          // P1-3.5 (UI 优化方案 2026-09-13): HTML 产物沙盒 iframe 渲染。
          // sandbox="allow-scripts" 允许 JS 执行但阻止跨域/顶层导航/表单提交。
          // right-panel R2 批次 A: key 随刷新计数重挂载 —— agent 迭代产物后
          // 点刷新立即看到新画面（srcDoc 同值不会触发 iframe 重载）。
          <iframe
            key={htmlReloadKey}
            srcDoc={content.content ?? ''}
            sandbox="allow-scripts"
            title={artifact.name}
            className="w-full h-full min-h-[24rem] rounded border border-border bg-white"
            data-testid="html-artifact-preview"
          />
        ) : content.kind === 'docx' || content.kind === 'xlsx' || content.kind === 'pptx' ? (
          content.structured ? (
            // Round B P3: 结构化路径 —— 与 Office 页同一组件渲染
            <div data-testid="office-structured-preview">
              {content.kind === 'docx' && (
                <WordPreview data={content.structured as OfficeWordReadResult} />
              )}
              {content.kind === 'xlsx' && (
                <ExcelPreview data={content.structured as OfficeExcelReadResult} />
              )}
              {content.kind === 'pptx' && (
                <PptPreview data={content.structured as OfficePptReadResult} />
              )}
            </div>
          ) : (
            // 降级路径（旧后端 / structured 序列化失败）：受控 HTML —— 后端
            // 已 html.escape 全转义；白底容器保证 dark 模式下文字可读
            <div
              data-testid="office-preview"
              className="office-preview bg-white text-black text-sm rounded border border-border p-3 [&_h2]:text-base [&_h2]:font-bold [&_h2]:my-2 [&_h3]:text-sm [&_h3]:font-semibold [&_h3]:my-2 [&_p]:my-1 [&_table]:border-collapse [&_table]:w-full [&_th]:border [&_th]:border-gray-300 [&_th]:px-2 [&_th]:py-0.5 [&_th]:bg-gray-50 [&_td]:border [&_td]:border-gray-300 [&_td]:px-2 [&_td]:py-0.5 [&_td]:align-top"
              dangerouslySetInnerHTML={{ __html: content.html ?? '' }}
            />
          )
        ) : content.kind === 'code' || content.kind === 'json' ? (
          // right-panel R2 批次 A: Shiki 语法高亮（消息流同源）；语言按扩展名
          // 推断，json kind 直接映射 json；未识别回落纯文本
          <ShikiCodeBlock language={content.kind === 'json' ? 'json' : langFromName(artifact.name)}>
            {content.content ?? ''}
          </ShikiCodeBlock>
        ) : content.kind === 'markdown' ? (
          // right-panel R2 批次 A: 默认渲染视图，header 可切源码（编辑态除外）
          mdRendered ? (
            <MarkdownRendered text={content.content ?? ''} />
          ) : (
            <ShikiCodeBlock language="markdown">{content.content ?? ''}</ShikiCodeBlock>
          )
        ) : content.kind === 'csv' ? (
          <CsvPreview text={content.content ?? ''} />
        ) : (
          <pre className="whitespace-pre-wrap text-sm">{content.content}</pre>
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
