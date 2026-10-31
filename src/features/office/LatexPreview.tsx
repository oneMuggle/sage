import { useState, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeKatex from 'rehype-katex';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';

import type { LatexBlock, LatexStructured, LatexWarning } from './latexTypes';

const MD_REMARK = [remarkGfm, remarkMath];
const MD_COMPONENTS = {
  p: ({ children }: { children?: ReactNode }) => <>{children}</>,
};

function MarkdownText({ text }: { text: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={MD_REMARK}
      rehypePlugins={[rehypeKatex]}
      components={MD_COMPONENTS}
    >
      {text}
    </ReactMarkdown>
  );
}

function WarningList({ warnings }: { warnings: LatexWarning[] }) {
  if (warnings.length === 0) return null;
  return (
    <div
      className="rounded border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-text-secondary"
      data-testid="latex-warnings"
    >
      <div className="font-medium text-text mb-1">解析警告（{warnings.length}）</div>
      <ul className="list-disc pl-4 space-y-0.5">
        {warnings.map((warning, index) => (
          <li key={`${warning.code}-${index}`}>
            <span className="font-mono text-xs text-muted">{warning.code}</span>
            {' · '}
            {warning.message}
            {warning.anchor ? (
              <span className="text-muted">
                {' '}
                （{warning.anchor.file}:{warning.anchor.line}）
              </span>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function FigureBlock({ block }: { block: LatexBlock }) {
  return (
    <figure className="my-4 text-center">
      {block.src ? (
        <img
          src={block.src}
          alt={block.caption || block.label || 'LaTeX figure'}
          className="max-w-full mx-auto rounded border border-border"
        />
      ) : (
        <div className="text-xs text-muted border border-dashed border-border rounded p-4">
          图片暂未内联预览{block.label ? ` · ${block.label}` : ''}
        </div>
      )}
      {block.caption ? (
        <figcaption className="mt-1 text-xs text-muted">
          <MarkdownText text={block.caption} />
        </figcaption>
      ) : null}
    </figure>
  );
}

function TableBlock({ block }: { block: LatexBlock }) {
  return (
    <div className="my-4 overflow-auto">
      {block.caption ? (
        <div className="text-xs text-muted mb-1">
          <MarkdownText text={block.caption} />
        </div>
      ) : null}
      <table className="text-xs border-collapse">
        {block.headers && block.headers.length > 0 ? (
          <thead>
            <tr>
              {block.headers.map((cell, index) => (
                <th key={index} className="border px-2 py-1 bg-bg-hover text-left">
                  <MarkdownText text={cell} />
                </th>
              ))}
            </tr>
          </thead>
        ) : null}
        <tbody>
          {(block.rows ?? []).slice(0, 500).map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, cellIndex) => (
                <td key={cellIndex} className="border px-2 py-1 align-top">
                  <MarkdownText text={cell} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function HeadingBlock({ block }: { block: LatexBlock }) {
  const level = Math.min(Math.max(block.level ?? 1, 1), 6);
  const content = <MarkdownText text={block.text ?? ''} />;
  if (level === 1) return <h1 className="text-xl font-semibold mt-5 mb-2">{content}</h1>;
  if (level === 2) return <h2 className="text-lg font-semibold mt-4 mb-1.5">{content}</h2>;
  if (level === 3) return <h3 className="text-base font-semibold mt-3 mb-1">{content}</h3>;
  if (level === 4) return <h4 className="text-sm font-semibold mt-3 mb-1">{content}</h4>;
  if (level === 5) return <h5 className="text-sm font-semibold mt-2 mb-1">{content}</h5>;
  return <h6 className="text-sm font-semibold mt-2 mb-1">{content}</h6>;
}

function BlockView({ block }: { block: LatexBlock }) {
  switch (block.type) {
    case 'heading':
      return <HeadingBlock block={block} />;
    case 'paragraph':
      return (
        <p className="my-2 text-sm leading-relaxed">
          <MarkdownText text={block.text ?? ''} />
        </p>
      );
    case 'list':
      return block.ordered ? (
        <ol className="list-decimal pl-6 my-2 text-sm space-y-1">
          {(block.items ?? []).map((item, index) => (
            <li key={index}>
              <MarkdownText text={item.text} />
            </li>
          ))}
        </ol>
      ) : (
        <ul className="list-disc pl-6 my-2 text-sm space-y-1">
          {(block.items ?? []).map((item, index) => (
            <li key={index}>
              <MarkdownText text={item.text} />
            </li>
          ))}
        </ul>
      );
    case 'equation':
      return (
        <div className="my-3 overflow-x-auto text-center">
          <MarkdownText text={`$$\n${block.latex ?? ''}\n$$`} />
        </div>
      );
    case 'figure':
      return <FigureBlock block={block} />;
    case 'table':
      return <TableBlock block={block} />;
    case 'bibliography':
      return (
        <section className="my-4">
          <h3 className="text-sm font-semibold mb-1">参考文献</h3>
          <ol className="list-decimal pl-6 text-xs space-y-1">
            {(block.entries ?? []).map((entry) => (
              <li key={entry.key}>
                <span className="text-muted">[{entry.key}]</span> <MarkdownText text={entry.text} />
              </li>
            ))}
          </ol>
        </section>
      );
    case 'code':
      return (
        <pre className="my-3 text-xs bg-bg-subtle rounded p-3 overflow-auto whitespace-pre-wrap">
          {block.text ?? ''}
        </pre>
      );
    case 'quote':
      return (
        <blockquote className="my-2 border-l-2 border-border pl-3 text-sm text-text-secondary">
          <MarkdownText text={block.text ?? ''} />
        </blockquote>
      );
    default:
      return block.text ? (
        <p className="my-2 text-sm">
          <MarkdownText text={block.text} />
        </p>
      ) : null;
  }
}

export interface LatexPreviewProps {
  data: LatexStructured;
  /** Raw .tex source; enables the source/preview toggle when provided. */
  source?: string;
  name?: string;
}

export function LatexPreview({ data, source, name }: LatexPreviewProps) {
  const [showSource, setShowSource] = useState(false);
  const title = data.metadata?.title || name || data.source_path;
  const authors = data.metadata?.authors ?? [];
  const includes = data.includes ?? [];
  const blockCount = data.blocks?.length ?? 0;

  const header = (
    <header className="mb-4 border-b border-border pb-3">
      <div className="text-lg font-semibold">{title}</div>
      {authors.length > 0 ? (
        <div className="text-xs text-muted mt-1">{authors.join(' · ')}</div>
      ) : null}
      <div className="text-xs text-muted mt-1">
        {data.metadata?.document_class ? `${data.metadata.document_class} · ` : ''}
        {blockCount} blocks
        {includes.length > 1 ? ` · ${includes.length} files` : ''}
      </div>
    </header>
  );

  return (
    <div className="h-full overflow-auto p-3" data-testid="latex-preview">
      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="text-xs text-muted truncate">{data.source_path}</div>
        {source ? (
          <button
            type="button"
            className="px-2 py-0.5 text-xs rounded border border-border hover:bg-bg-hover"
            onClick={() => setShowSource((value) => !value)}
            data-testid="latex-source-toggle"
          >
            {showSource ? '预览' : '源码'}
          </button>
        ) : null}
      </div>
      {showSource ? (
        <pre className="text-xs whitespace-pre-wrap break-words" data-testid="latex-source">
          {source}
        </pre>
      ) : (
        <>
          {header}
          <WarningList warnings={data.warnings ?? []} />
          <div className="mt-3">
            {(data.blocks ?? []).map((block, index) => (
              <BlockView key={`${block.type}-${index}`} block={block} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
