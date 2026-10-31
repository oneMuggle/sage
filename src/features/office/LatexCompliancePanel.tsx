import { useState } from 'react';

import {
  checkLatexCompliance,
  type LatexComplianceCheck,
  type LatexComplianceResult,
} from '../../shared/api/latexApi';
import { useCurrentWorkspace } from '../../shared/lib/workspaceContext';

import { joinWorkspacePath } from './latexPath';

function splitList(value: string): string[] {
  return value
    .split(/[,，;；]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function statusLabel(status: LatexComplianceCheck['status']): string {
  if (status === 'pass') return '通过';
  if (status === 'warn') return '警告';
  if (status === 'fail') return '失败';
  return '跳过';
}

function statusClass(status: LatexComplianceCheck['status']): string {
  if (status === 'pass') return 'text-success';
  if (status === 'warn') return 'text-warning';
  if (status === 'fail') return 'text-error';
  return 'text-muted';
}

function issueAnchor(issue: LatexComplianceResult['issues'][number]): string {
  if (issue.anchor?.page) return `第 ${issue.anchor.page} 页`;
  if (issue.anchor?.line) return `line ${issue.anchor.line}`;
  return issue.anchor?.file ?? '';
}

export interface LatexCompliancePanelProps {
  workspacePath?: string | null;
}

export function LatexCompliancePanel({
  workspacePath: wsOverride,
}: LatexCompliancePanelProps) {
  const activeWorkspace = useCurrentWorkspace() ?? null;
  const workspacePath = wsOverride ?? activeWorkspace;
  const canUse = Boolean(workspacePath && workspacePath.trim());

  const [texPath, setTexPath] = useState('');
  const [pdfPath, setPdfPath] = useState('');
  const [sections, setSections] = useState('');
  const [metadata, setMetadata] = useState('title, author, abstract');
  const [pageSizes, setPageSizes] = useState('');
  const [minPages, setMinPages] = useState('');
  const [maxPages, setMaxPages] = useState('');
  const [minDpi, setMinDpi] = useState('150');
  const [requireFonts, setRequireFonts] = useState(true);
  const [forbidden, setForbidden] = useState('write18');
  const [result, setResult] = useState<LatexComplianceResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleCheck = async () => {
    if (!canUse || !texPath.trim()) {
      setError('请先绑定工作区并填写 .tex 路径');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const minPageNumber = Number.parseInt(minPages, 10);
      const maxPageNumber = Number.parseInt(maxPages, 10);
      const dpiNumber = Number.parseFloat(minDpi);
      setResult(
        await checkLatexCompliance(
          workspacePath!,
          joinWorkspacePath(workspacePath!, texPath),
          pdfPath.trim() ? joinWorkspacePath(workspacePath!, pdfPath) : undefined,
          {
            required_sections: splitList(sections),
            required_metadata: splitList(metadata),
            allowed_page_sizes: splitList(pageSizes),
            required_min_pages: Number.isFinite(minPageNumber) ? minPageNumber : null,
            required_max_pages: Number.isFinite(maxPageNumber) ? maxPageNumber : null,
            require_embedded_fonts: requireFonts,
            min_image_dpi: Number.isFinite(dpiNumber) ? dpiNumber : 150,
            forbidden_commands: splitList(forbidden),
          },
        ),
      );
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      className="flex flex-col gap-3 rounded border border-border p-4"
      data-testid="latex-compliance-panel"
    >
      <header>
        <h2 className="text-base font-semibold">LaTeX 投稿合规检查</h2>
        <p className="text-xs text-muted">
          按规范档案同时检查源码与可选 PDF：必需章节/元数据、页数/页面尺寸、字体嵌入、图片
          DPI、禁用命令。只读，不修改文件、不执行 TeX。
        </p>
      </header>

      <div className="flex gap-2">
        <input
          className="flex-1 rounded border border-border bg-bg px-2 py-1 text-sm"
          placeholder="paper/main.tex"
          value={texPath}
          onChange={(event) => setTexPath(event.target.value)}
          data-testid="latex-compliance-tex"
        />
        <input
          className="flex-1 rounded border border-border bg-bg px-2 py-1 text-sm"
          placeholder="可选：paper/main.pdf"
          value={pdfPath}
          onChange={(event) => setPdfPath(event.target.value)}
          data-testid="latex-compliance-pdf"
        />
      </div>

      <div className="grid grid-cols-2 gap-2">
        <input
          className="rounded border border-border bg-bg px-2 py-1 text-sm"
          placeholder="必需章节，如 Introduction, Conclusion"
          value={sections}
          onChange={(event) => setSections(event.target.value)}
          data-testid="latex-compliance-sections"
        />
        <input
          className="rounded border border-border bg-bg px-2 py-1 text-sm"
          placeholder="必需元数据，如 title, author, abstract"
          value={metadata}
          onChange={(event) => setMetadata(event.target.value)}
          data-testid="latex-compliance-metadata"
        />
        <input
          className="rounded border border-border bg-bg px-2 py-1 text-sm"
          placeholder="允许页面尺寸，如 A4, Letter"
          value={pageSizes}
          onChange={(event) => setPageSizes(event.target.value)}
          data-testid="latex-compliance-page-sizes"
        />
        <input
          className="rounded border border-border bg-bg px-2 py-1 text-sm"
          placeholder="禁用命令，如 write18, todo"
          value={forbidden}
          onChange={(event) => setForbidden(event.target.value)}
          data-testid="latex-compliance-forbidden"
        />
        <input
          className="rounded border border-border bg-bg px-2 py-1 text-sm"
          placeholder="最小页数"
          value={minPages}
          onChange={(event) => setMinPages(event.target.value)}
          data-testid="latex-compliance-min-pages"
        />
        <input
          className="rounded border border-border bg-bg px-2 py-1 text-sm"
          placeholder="最大页数"
          value={maxPages}
          onChange={(event) => setMaxPages(event.target.value)}
          data-testid="latex-compliance-max-pages"
        />
        <input
          className="rounded border border-border bg-bg px-2 py-1 text-sm"
          placeholder="图片 DPI 阈值"
          value={minDpi}
          onChange={(event) => setMinDpi(event.target.value)}
          data-testid="latex-compliance-dpi"
        />
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={requireFonts}
            onChange={(event) => setRequireFonts(event.target.checked)}
            data-testid="latex-compliance-fonts"
          />
          要求字体全部嵌入
        </label>
      </div>

      <button
        type="button"
        className="w-fit rounded bg-accent px-3 py-1 text-sm text-white hover:opacity-90 disabled:opacity-50"
        onClick={handleCheck}
        disabled={busy}
        data-testid="latex-compliance-run"
      >
        {busy ? '检查中…' : '开始合规检查'}
      </button>

      {result ? (
        <div
          className="flex flex-col gap-2 rounded border border-border bg-bg-subtle p-2 text-xs"
          data-testid="latex-compliance-result"
        >
          <div className="font-medium">
            {result.ok ? '合规检查通过' : '存在不合规项'} · 错误{' '}
            {result.summary.severity.error} · 警告 {result.summary.severity.warning}
          </div>
          <ul className="flex flex-col gap-1">
            {result.checks.map((check) => (
              <li key={check.id} className="flex items-center gap-2">
                <span className={`font-medium ${statusClass(check.status)}`}>
                  {statusLabel(check.status)}
                </span>
                <span>{check.label}</span>
                {check.message ? <span className="text-muted">{check.message}</span> : null}
              </li>
            ))}
          </ul>
          {result.issues.length > 0 ? (
            <ul className="mt-1 flex flex-col gap-1">
              {result.issues.map((issue, index) => (
                <li
                  key={`${issue.rule_id}:${index}`}
                  className="rounded border border-border p-1"
                >
                  <div className="font-medium">
                    {issue.source} · {issue.rule_id}
                    {issueAnchor(issue) ? ` · ${issueAnchor(issue)}` : ''}
                  </div>
                  <div>{issue.message}</div>
                  {issue.fix_hint ? (
                    <div className="text-muted">建议：{issue.fix_hint}</div>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      {error ? <div className="text-sm text-error">{error}</div> : null}
    </section>
  );
}
