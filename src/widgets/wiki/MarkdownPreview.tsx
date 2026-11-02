// Markdown Preview - 共享 Markdown 渲染器（GFM 排版 / 代码块 / 表格统一）
import { Markdown } from '../markdown';

export function MarkdownPreview({ content }: { content: string }) {
  return <Markdown content={content} tier="minimal" className="p-4" testId="wiki-md-preview" />;
}

export default MarkdownPreview;

export interface WikiMarkdownPreviewAuditInput {
  markdownContent: string;
  maxPreviewBytes: number;
  sanitizeLinksEnabled: boolean;
}

export interface WikiMarkdownPreviewAuditReport {
  contentByteLength: number;
  withinByteLimit: boolean;
  healthy: boolean;
  issueCodes: string[];
}

// eslint-disable-next-line react-refresh/only-export-components
export function evaluateWikiMarkdownPreviewGovernanceAudit(
  input: WikiMarkdownPreviewAuditInput,
): WikiMarkdownPreviewAuditReport {
  const issueCodes: string[] = [];
  const contentByteLength = new TextEncoder().encode(input.markdownContent).length;
  if (input.maxPreviewBytes <= 0) {
    issueCodes.push('WIKI_MARKDOWN_PREVIEW_LIMIT_INVALID');
  }
  const withinByteLimit =
    input.maxPreviewBytes > 0 && contentByteLength <= input.maxPreviewBytes;
  if (input.maxPreviewBytes > 0 && !withinByteLimit) {
    issueCodes.push('WIKI_MARKDOWN_PREVIEW_SIZE_EXCEEDED');
  }
  if (!input.sanitizeLinksEnabled) {
    issueCodes.push('WIKI_MARKDOWN_PREVIEW_UNSANITIZED_LINKS');
  }
  return {
    contentByteLength,
    withinByteLimit,
    healthy: issueCodes.length === 0,
    issueCodes,
  };
}
