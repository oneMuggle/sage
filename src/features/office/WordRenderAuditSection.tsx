/**
 * WordRenderAuditSection (M5c) — 渲染级校验。
 *
 * DOCX → PDF 后复核页面尺寸、页边距、字体与页码。挂在 DocumentAuditPanel
 * 底部，手动触发：转换依赖 LibreOffice / Word COM，不应随面板挂载自动运行。
 * 无转换器时后端返回 rendered=false + warnings，此处展示降级原因而非报错。
 */

import { useState } from 'react';

import { officeApi } from '../../shared/api/officeApi';
import type { WordRenderAuditResult, WordRenderIssue } from '../../shared/api/wordAuditTypes';

const CATEGORY_LABEL: Record<WordRenderIssue['category'], string> = {
  page: '页面',
  margin: '页边距',
  font: '字体',
  page_number: '页码',
};

const SEVERITY_CLASS: Record<string, string> = {
  error: 'text-error border-error/40 bg-error/10',
  warning: 'text-warning border-warning/40 bg-warning/10',
};

type MarginSide = 'top' | 'bottom' | 'left' | 'right';

const MARGIN_SIDES: Array<{ key: MarginSide; label: string }> = [
  { key: 'top', label: '上' },
  { key: 'bottom', label: '下' },
  { key: 'left', label: '左' },
  { key: 'right', label: '右' },
];

const EMPTY_MARGINS: Record<MarginSide, string> = {
  top: '',
  bottom: '',
  left: '',
  right: '',
};

function parseMargins(raw: Record<MarginSide, string>): Record<string, number> | undefined {
  const margins: Record<string, number> = {};
  for (const { key } of MARGIN_SIDES) {
    const value = raw[key].trim();
    if (!value) continue;
    const parsed = Number(value);
    if (Number.isFinite(parsed) && parsed >= 0) {
      margins[key] = parsed;
    }
  }
  return Object.keys(margins).length > 0 ? margins : undefined;
}

export interface WordRenderAuditSectionProps {
  workspacePath: string;
  filePath: string;
}

export function WordRenderAuditSection({
  workspacePath,
  filePath,
}: WordRenderAuditSectionProps) {
  const [expectedSize, setExpectedSize] = useState<'' | 'A4' | 'Letter'>('');
  const [requirePageNumber, setRequirePageNumber] = useState(false);
  const [allowedFonts, setAllowedFonts] = useState('');
  const [margins, setMargins] = useState<Record<MarginSide, string>>(EMPTY_MARGINS);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<WordRenderAuditResult | null>(null);

  const run = async () => {
    if (running) return;
    setRunning(true);
    setError(null);
    try {
      const fonts = allowedFonts
        .split(/[,，;；\n]+/)
        .map((name) => name.trim())
        .filter(Boolean);
      const marginValues = parseMargins(margins);
      const res = await officeApi.renderAuditWord({
        workspace_path: workspacePath,
        file_path: filePath,
        ...(expectedSize ? { expected_size: expectedSize } : {}),
        ...(marginValues ? { margins_cm: marginValues } : {}),
        ...(fonts.length > 0 ? { allowed_fonts: fonts } : {}),
        require_page_number: requirePageNumber,
      });
      setResult(res);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  const updateMargin = (key: MarginSide, value: string) => {
    setMargins((prev) => ({ ...prev, [key]: value }));
  };

  const issues = result?.issues ?? [];
  const errorCount = issues.filter((issue) => issue.severity === 'error').length;
  const warningCount = issues.length - errorCount;

  return (
    <div
      className="mt-2 flex flex-col gap-2 rounded border border-border p-3"
      data-testid="word-render-audit-section"
    >
      <header className="flex flex-wrap items-start gap-2">
        <div className="min-w-0">
          <h4 className="text-xs font-semibold">渲染级校验</h4>
          <p className="text-ui-2xs text-muted">
            渲染为 PDF 后复核页面尺寸 / 页边距 / 字体 / 页码；需要本机 DOCX→PDF 转换器
          </p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2 text-xs">
          <select
            value={expectedSize}
            onChange={(event) => setExpectedSize(event.target.value as '' | 'A4' | 'Letter')}
            data-testid="word-render-size"
            aria-label="期望页面尺寸"
            className="rounded border border-border bg-surface px-2 py-1 text-xs"
          >
            <option value="">页面尺寸：不校验</option>
            <option value="A4">A4</option>
            <option value="Letter">Letter</option>
          </select>
          <label className="flex items-center gap-1 text-xs text-muted">
            <input
              type="checkbox"
              checked={requirePageNumber}
              onChange={(event) => setRequirePageNumber(event.target.checked)}
              data-testid="word-render-page-number"
            />
            要求页码
          </label>
          <button
            type="button"
            onClick={() => void run()}
            disabled={running}
            data-testid="word-render-run"
            className="rounded border border-border px-2 py-1 text-xs text-text-secondary hover:bg-bg-hover disabled:opacity-50"
          >
            {running ? '渲染校验中…' : '渲染校验'}
          </button>
        </div>
      </header>

      <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
        <label className="flex items-center gap-1">
          字体白名单
          <input
            type="text"
            value={allowedFonts}
            onChange={(event) => setAllowedFonts(event.target.value)}
            placeholder="宋体, Times New Roman（可选）"
            data-testid="word-render-fonts"
            className="w-56 rounded border border-border bg-surface px-2 py-1 text-xs"
          />
        </label>
        {MARGIN_SIDES.map(({ key, label }) => (
          <label key={key} className="flex items-center gap-1">
            {label}
            <input
              type="number"
              min={0}
              step={0.1}
              value={margins[key]}
              onChange={(event) => updateMargin(key, event.target.value)}
              placeholder="cm"
              data-testid={`word-render-margin-${key}`}
              className="w-16 rounded border border-border bg-surface px-2 py-1 text-xs"
            />
          </label>
        ))}
      </div>

      {error && (
        <p className="text-xs text-error" data-testid="word-render-error">
          {error}
        </p>
      )}

      {result && (
        <div className="flex flex-col gap-2" data-testid="word-render-result">
          {!result.rendered ? (
            <p className="text-xs text-warning" data-testid="word-render-unrendered">
              未渲染：当前环境没有可用的 DOCX→PDF 转换器，渲染级校验无法执行。
            </p>
          ) : (
            <>
              <p className="text-xs" data-testid="word-render-summary">
                已渲染 {result.page_count} 页 · {result.method ?? 'converter'} · {errorCount} 错误 ·{' '}
                {warningCount} 警告
              </p>
              {issues.length === 0 ? (
                <p className="text-xs text-success" data-testid="word-render-empty">
                  渲染检查通过。
                </p>
              ) : (
                <ul className="flex flex-col gap-2" data-testid="word-render-issues">
                  {issues.map((issue, index) => (
                    <li
                      key={`${issue.page_index}-${issue.category}-${index}`}
                      data-testid={`word-render-issue-${index}`}
                      className="rounded border border-border p-2"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <span
                          className={`rounded border px-1.5 py-0.5 text-ui-2xs ${
                            SEVERITY_CLASS[issue.severity] ?? 'border-border bg-bg-subtle text-muted'
                          }`}
                        >
                          {issue.severity === 'error' ? '错误' : '警告'}
                        </span>
                        <span className="text-ui-2xs text-text-secondary">
                          {CATEGORY_LABEL[issue.category]}
                        </span>
                        <span className="text-ui-2xs text-muted">第 {issue.page_index + 1} 页</span>
                      </div>
                      <p className="mt-1 text-sm text-text">{issue.message}</p>
                      {(issue.expected || issue.actual) && (
                        <p className="mt-0.5 text-xs text-muted">
                          期望 {issue.expected ?? '-'} · 实测 {issue.actual ?? '-'}
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
          {result.warnings.length > 0 && (
            <ul className="text-xs text-muted" data-testid="word-render-warnings">
              {result.warnings.map((warning, index) => (
                <li key={`${warning.code}-${index}`}>
                  {warning.code}: {warning.message}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
