// src/widgets/chat/preview/FileContentRenderer.tsx
//
// 统一文件内容渲染器（feat/file-reference-preview）——从 ArtifactViewer 抽出
// 的按类型分发逻辑：图片 / PDF / HTML / Office 三件套 / 代码 / Markdown / CSV /
// 纯文本。产物预览（ArtifactViewer）与消息内文件预览（FilePreviewPanel）
// 共用同一套渲染，保证两端视觉与行为同源。
import { ClipboardCopy } from 'lucide-react';
import { useCallback, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeKatex from 'rehype-katex';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';

import { ExcelPreview, PptPreview, WordPreview } from '../../../features/office';
// 2026-10-29（基线同步）: Word 产物默认走 docx-preview 原生渲染，结构化段落
// 视图保留为切换/降级项。
import { DocxBlobPreview } from '../../../features/office/DocxBlobPreview';
import { LatexPreview } from '../../../features/office/LatexPreview';
import type { LatexStructured } from '../../../features/office/latexTypes';
import type {
  OfficeExcelReadResult,
  OfficePptReadResult,
  OfficeWordReadResult,
} from '../../../shared/api/types';
import { langFromPath } from '../../../shared/lib/fileLang';
import { ShikiCodeBlock } from '../ShikiCodeBlock';

/** artifact content 与 workspace preview 的公共响应形状（后端同一套字段） */
export interface PreviewContentPayload {
  ok: boolean;
  error?: string;
  kind?: string;
  content?: string;
  data_url?: string;
  html?: string;
  structured?: unknown;
  truncated?: boolean;
}

interface FileContentRendererProps {
  content: PreviewContentPayload;
  /** 文件名/路径——用于 alt、iframe title 与代码语言推断 */
  name: string;
  /** Markdown 渲染视图 / 源码切换（默认渲染） */
  mdRendered?: boolean;
  /** HTML 预览刷新 key（重挂载 iframe 使 srcDoc 同值也能刷新） */
  htmlReloadKey?: number;
  /** docx 是否优先 Word 版式（docx-preview）；默认 true，切换/失败回退结构化 */
  docxFidelity?: boolean;
  /** docx-preview 渲染失败回调（上层据此回退结构化视图） */
  onDocxFidelityError?: () => void;
}

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
  const handleCopy = useCallback(() => {
    void navigator.clipboard?.writeText(text)?.catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }, [text]);
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
          onClick={handleCopy}
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

export function FileContentRenderer({
  content,
  name,
  mdRendered = true,
  htmlReloadKey = 0,
  docxFidelity = true,
  onDocxFidelityError,
}: FileContentRendererProps) {
  if (!content.ok) {
    return <div className="text-sm text-error">{content.error ?? '加载失败'}</div>;
  }
  if (content.kind === 'image') {
    return <img src={content.data_url} alt={name} className="max-w-full" />;
  }
  if (content.kind === 'pdf') {
    // Chromium 内置 PDF viewer 内嵌渲染,零依赖
    return (
      <iframe
        src={content.data_url}
        title={name}
        className="w-full h-full min-h-[24rem] rounded border border-border"
      />
    );
  }
  if (content.kind === 'html') {
    // 沙盒 iframe：允许脚本但阻止跨域/顶层导航/表单提交
    return (
      <iframe
        key={htmlReloadKey}
        srcDoc={content.content ?? ''}
        sandbox="allow-scripts"
        title={name}
        className="w-full h-full min-h-[24rem] rounded border border-border bg-white"
        data-testid="html-artifact-preview"
      />
    );
  }
  if (content.kind === 'docx' || content.kind === 'xlsx' || content.kind === 'pptx') {
    if (content.kind === 'docx' && content.data_url && docxFidelity) {
      // 2026-10-29（基线同步）: Word 版式 —— docx-preview 直接解析原文二进制
      // （页宽/字体/表格/图片），失败由上层回退结构化视图。
      return <DocxBlobPreview dataUrl={content.data_url} onError={onDocxFidelityError} />;
    }
    if (content.structured) {
      // 结构化路径 —— 与 Office 页同一组件渲染
      return (
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
      );
    }
    // 降级路径（structured 缺失）：后端已 html.escape 全转义的受控 HTML
    return (
      <div
        data-testid="office-preview"
        className="office-preview bg-white text-black text-sm rounded border border-border p-3 [&_h2]:text-base [&_h2]:font-bold [&_h2]:my-2 [&_h3]:text-sm [&_h3]:font-semibold [&_h3]:my-2 [&_p]:my-1 [&_table]:border-collapse [&_table]:w-full [&_th]:border [&_th]:border-gray-300 [&_th]:px-2 [&_th]:py-0.5 [&_th]:bg-gray-50 [&_td]:border [&_td]:border-gray-300 [&_td]:px-2 [&_td]:py-0.5 [&_td]:align-top"
        dangerouslySetInnerHTML={{ __html: content.html ?? '' }}
      />
    );
  }
  if (content.kind === 'code' || content.kind === 'json') {
    return (
      <ShikiCodeBlock language={content.kind === 'json' ? 'json' : langFromPath(name)}>
        {content.content ?? ''}
      </ShikiCodeBlock>
    );
  }
  if (content.kind === 'markdown') {
    return mdRendered ? (
      <MarkdownRendered text={content.content ?? ''} />
    ) : (
      <ShikiCodeBlock language="markdown">{content.content ?? ''}</ShikiCodeBlock>
    );
  }
  if (content.kind === 'csv') {
    return <CsvPreview text={content.content ?? ''} />;
  }
  if (content.kind === 'latex') {
    const structured = content.structured as LatexStructured | undefined;
    if (structured && Array.isArray(structured.blocks)) {
      return <LatexPreview data={structured} source={content.content} name={name} />;
    }
    return <ShikiCodeBlock language="latex">{content.content ?? ''}</ShikiCodeBlock>;
  }
  return <pre className="whitespace-pre-wrap text-sm">{content.content}</pre>;
}
