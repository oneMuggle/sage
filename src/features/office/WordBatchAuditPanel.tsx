/**
 * WordBatchAuditPanel (M5c) — 工作区批量审校。
 *
 * 挂在 /office 页底部面板区：glob / 文件数上限 / 规则包 → POST
 * /office/word/audit/batch，展示汇总、逐文件问题与 Markdown 报告。
 * 后端逐文件隔离失败，这里只做展示；单文件问题最多展开 20 条。
 */

import { useEffect, useState } from 'react';

import { officeApi } from '../../shared/api/officeApi';
import type { WordBatchAuditResult, WordRulePackSummary } from '../../shared/api/wordAuditTypes';

import { DEFAULT_PACK_ID, DEFAULT_PACKS } from './wordRulePackDefaults';

const MAX_FILES_LIMIT = 50;
const ISSUES_PREVIEW_LIMIT = 20;

function parseMaxFiles(raw: string): number | undefined {
  const parsed = Number(raw.trim());
  if (!Number.isFinite(parsed) || parsed < 1) return undefined;
  return Math.min(Math.floor(parsed), MAX_FILES_LIMIT);
}

export interface WordBatchAuditPanelProps {
  workspacePath: string;
}

export function WordBatchAuditPanel({ workspacePath }: WordBatchAuditPanelProps) {
  const [packs, setPacks] = useState<WordRulePackSummary[]>([]);
  const [packId, setPackId] = useState(DEFAULT_PACK_ID);
  const [pattern, setPattern] = useState('**/*.docx');
  const [maxFiles, setMaxFiles] = useState(String(ISSUES_PREVIEW_LIMIT));
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<WordBatchAuditResult | null>(null);
  const [reportOpen, setReportOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void officeApi
      .listWordRulePacks({ workspacePath })
      .then((list) => {
        if (!cancelled && list.ok && list.packs.length > 0) {
          setPacks(list.packs);
        }
      })
      .catch(() => {
        // 列表失败不阻塞批量审校：默认内置包仍可用
      });
    return () => {
      cancelled = true;
    };
  }, [workspacePath]);

  const run = async () => {
    if (running) return;
    setRunning(true);
    setError(null);
    try {
      const limit = parseMaxFiles(maxFiles);
      const res = await officeApi.batchAuditWord({
        workspace_path: workspacePath,
        ...(pattern.trim() ? { pattern: pattern.trim() } : {}),
        ...(limit !== undefined ? { max_files: limit } : {}),
        rulepack_id: packId,
        include_report: true,
      });
      setResult(res);
      setReportOpen(false);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  const packOptions = packs.length > 0 ? packs : DEFAULT_PACKS;

  return (
    <section
      className="mt-4 flex flex-col gap-3 rounded border border-border p-4"
      data-testid="word-batch-audit-panel"
    >
      <header className="flex flex-wrap items-start gap-2">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold">批量审校</h3>
          <p className="text-xs text-muted">
            按通配符扫描工作区内 .docx，逐文件运行规则包并汇总问题
          </p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <input
            type="text"
            value={pattern}
            onChange={(event) => setPattern(event.target.value)}
            placeholder="**/*.docx"
            aria-label="文件匹配模式"
            data-testid="word-batch-pattern"
            className="w-44 rounded border border-border bg-surface px-2 py-1 text-xs"
          />
          <label className="flex items-center gap-1 text-xs text-muted">
            最多
            <input
              type="number"
              min={1}
              max={MAX_FILES_LIMIT}
              step={1}
              value={maxFiles}
              onChange={(event) => setMaxFiles(event.target.value)}
              aria-label="最多文件数"
              data-testid="word-batch-max-files"
              className="w-16 rounded border border-border bg-surface px-2 py-1 text-xs"
            />
            个文件
          </label>
          <select
            value={packId}
            onChange={(event) => setPackId(event.target.value)}
            data-testid="word-batch-pack"
            aria-label="规则包"
            className="rounded border border-border bg-surface px-2 py-1 text-xs"
          >
            {packOptions.map((pack) => (
              <option key={pack.id} value={pack.id}>
                {pack.name}
                {pack.origin === 'workspace' ? '（工作区）' : ''}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => void run()}
            disabled={running}
            data-testid="word-batch-run"
            className="rounded border border-border px-2 py-1 text-xs text-text-secondary hover:bg-bg-hover disabled:opacity-50"
          >
            {running ? '审校中…' : '运行批量审校'}
          </button>
        </div>
      </header>

      {error && (
        <p className="text-xs text-error" data-testid="word-batch-error">
          {error}
        </p>
      )}

      {result && (
        <>
          <div
            className="flex flex-wrap items-center gap-2 text-xs"
            data-testid="word-batch-summary"
          >
            <span className={result.ok ? 'text-success' : 'text-error'}>
              {result.ok ? '通过' : '存在错误'}
            </span>
            <span className="text-muted">
              {result.totals.files} 个文件（成功 {result.totals.ok_files} · 失败{' '}
              {result.totals.failed_files}）· {result.totals.error_count} 错误 ·{' '}
              {result.totals.warning_count} 警告
            </span>
            <span className="text-muted">{result.rule_pack_id}</span>
          </div>

          {result.files.length === 0 ? (
            <p className="text-xs text-muted" data-testid="word-batch-empty">
              没有匹配到可审校的文件。
            </p>
          ) : (
            <ul className="flex flex-col gap-2" data-testid="word-batch-files">
              {result.files.map((file, index) => (
                <li
                  key={`${file.source_path}-${index}`}
                  data-testid={`word-batch-file-${index}`}
                  className="rounded border border-border p-2"
                >
                  <details>
                    <summary className="flex flex-wrap items-center gap-2 text-xs">
                      <span className={file.ok ? 'text-success' : 'text-error'}>
                        {file.ok ? '通过' : '失败'}
                      </span>
                      <span className="min-w-0 break-all text-text-secondary">
                        {file.source_path}
                      </span>
                      <span className="ml-auto text-muted">
                        {file.error_count} 错误 · {file.warning_count} 警告
                      </span>
                    </summary>
                    {file.error && <p className="mt-1 text-xs text-error">{file.error}</p>}
                    {file.issues.length > 0 && (
                      <ul
                        className="mt-1 flex flex-col gap-1 text-xs"
                        data-testid={`word-batch-file-issues-${index}`}
                      >
                        {file.issues.slice(0, ISSUES_PREVIEW_LIMIT).map((issue, issueIndex) => (
                          <li key={`${issue.rule_id}-${issueIndex}`} className="text-text-secondary">
                            <span
                              className={issue.severity === 'error' ? 'text-error' : 'text-warning'}
                            >
                              {issue.severity === 'error' ? '错误' : '警告'}
                            </span>{' '}
                            {issue.rule_id}: {issue.message}
                          </li>
                        ))}
                        {file.issues.length > ISSUES_PREVIEW_LIMIT && (
                          <li className="text-muted">
                            还有 {file.issues.length - ISSUES_PREVIEW_LIMIT} 条，见下报告
                          </li>
                        )}
                      </ul>
                    )}
                  </details>
                </li>
              ))}
            </ul>
          )}

          {result.report_markdown && (
            <div className="flex flex-col gap-2">
              <button
                type="button"
                onClick={() => setReportOpen((prev) => !prev)}
                data-testid="word-batch-report-toggle"
                className="self-start rounded border border-border px-2 py-1 text-xs text-text-secondary hover:bg-bg-hover"
              >
                {reportOpen ? '收起报告' : '展开 Markdown 报告'}
              </button>
              {reportOpen && (
                <pre
                  className="max-h-80 overflow-auto whitespace-pre-wrap rounded border border-border bg-bg-subtle p-3 text-xs text-text-secondary"
                  data-testid="word-batch-report"
                >
                  {result.report_markdown}
                </pre>
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
}
