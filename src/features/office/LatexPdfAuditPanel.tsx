import { useState } from 'react';

import {
  auditLatexPdf,
  type LatexAuditIssue,
  type LatexPdfAuditResult,
} from '../../shared/api/latexApi';
import { useCurrentWorkspace } from '../../shared/lib/workspaceContext';

import { LatexPathPicker } from './LatexPathPicker';
import { joinWorkspacePath } from './latexPath';

function severityLabel(severity: LatexAuditIssue['severity']): string {
  if (severity === 'error') return '错误';
  if (severity === 'warning') return '警告';
  return '提示';
}

function issueAnchor(issue: LatexAuditIssue): string {
  if (issue.anchor?.page) return `第 ${issue.anchor.page} 页`;
  return issue.anchor?.file ?? '';
}

export interface LatexPdfAuditPanelProps {
  workspacePath?: string | null;
}

export function LatexPdfAuditPanel({
  workspacePath: wsOverride,
}: LatexPdfAuditPanelProps) {
  const activeWorkspace = useCurrentWorkspace() ?? null;
  const workspacePath = wsOverride ?? activeWorkspace;
  const canUse = Boolean(workspacePath && workspacePath.trim());

  const [pdfPath, setPdfPath] = useState('');
  const [minPages, setMinPages] = useState('');
  const [maxPages, setMaxPages] = useState('');
  const [minDpi, setMinDpi] = useState('150');
  const [result, setResult] = useState<LatexPdfAuditResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleAudit = async () => {
    if (!canUse || !pdfPath.trim()) {
      setError('请先绑定工作区并填写 .pdf 路径');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const minPageNumber = Number.parseInt(minPages, 10);
      const maxPageNumber = Number.parseInt(maxPages, 10);
      const dpiNumber = Number.parseFloat(minDpi);
      setResult(
        await auditLatexPdf(
          workspacePath!,
          joinWorkspacePath(workspacePath!, pdfPath),
          Number.isFinite(minPageNumber) ? minPageNumber : undefined,
          Number.isFinite(maxPageNumber) ? maxPageNumber : undefined,
          Number.isFinite(dpiNumber) ? dpiNumber : 150,
        ),
      );
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const embeddedFonts =
    result?.summary.fonts.filter((font) => font.embedded).length ?? 0;
  const totalFonts = result?.summary.fonts.length ?? 0;

  return (
    <section
      className="flex flex-col gap-3 rounded border border-border p-4"
      data-testid="latex-pdf-audit-panel"
    >
      <header>
        <h2 className="text-base font-semibold">PDF 版式审计</h2>
        <p className="text-xs text-muted">
          只读检查 PDF 的页数/页面尺寸、字体是否嵌入、图片有效 DPI。适合投稿前自检；
          不修改 PDF、不执行 TeX。
        </p>
      </header>

      <LatexPathPicker
        value={pdfPath}
        onChange={setPdfPath}
        title="选择 PDF"
        extensions={['pdf']}
        placeholder="paper/main.pdf"
        testId="latex-pdf-path"
      />
      <div className="flex flex-wrap gap-2">
        <input
          className="w-28 rounded border border-border bg-bg px-2 py-1 text-sm"
          placeholder="最小页数"
          value={minPages}
          onChange={(event) => setMinPages(event.target.value)}
          data-testid="latex-pdf-min-pages"
        />
        <input
          className="w-28 rounded border border-border bg-bg px-2 py-1 text-sm"
          placeholder="最大页数"
          value={maxPages}
          onChange={(event) => setMaxPages(event.target.value)}
          data-testid="latex-pdf-max-pages"
        />
        <input
          className="w-32 rounded border border-border bg-bg px-2 py-1 text-sm"
          placeholder="图片 DPI 阈值"
          value={minDpi}
          onChange={(event) => setMinDpi(event.target.value)}
          data-testid="latex-pdf-dpi"
        />
        <button
          type="button"
          className="rounded bg-accent px-3 py-1 text-sm text-white hover:opacity-90 disabled:opacity-50"
          onClick={handleAudit}
          disabled={busy}
          data-testid="latex-pdf-run"
        >
          {busy ? '审计中…' : '审计 PDF'}
        </button>
      </div>

      {result ? (
        <div
          className="rounded border border-border bg-bg-subtle p-2 text-xs"
          data-testid="latex-pdf-result"
        >
          <div className="font-medium">
            共 {result.summary.pages} 页 · {result.summary.page_size.label}（
            {result.summary.page_size.width}×{result.summary.page_size.height} pt） · 图片{' '}
            {result.summary.images_count} 张
          </div>
          <div className="text-muted mt-1">
            字体 {embeddedFonts}/{totalFonts} 已嵌入 · 最低图片 DPI：
            {result.summary.min_image_dpi ?? '无图片'}
          </div>
          {result.issues.length > 0 ? (
            <ul className="mt-2 flex flex-col gap-1">
              {result.issues.map((issue, index) => (
                <li
                  key={`${issue.rule_id}:${index}`}
                  className="rounded border border-border p-1"
                >
                  <div className="font-medium">
                    {severityLabel(issue.severity)} · {issue.rule_id}
                    {issueAnchor(issue) ? ` · ${issueAnchor(issue)}` : ''}
                  </div>
                  <div>{issue.message}</div>
                  {issue.fix_hint ? (
                    <div className="text-muted">建议：{issue.fix_hint}</div>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : (
            <div className="text-muted mt-1">未发现问题</div>
          )}
        </div>
      ) : null}

      {error ? <div className="text-sm text-error">{error}</div> : null}
    </section>
  );
}
