/**
 * DocumentAuditPanel (M2c) — Word 规则包审校 + 一键修复。
 *
 * 挂在 OfficePreviewPanel 的 word 工具栏下：选择规则包 → 运行确定性审校 →
 * 按严重级别过滤 → 点击 issue 定位到结构化预览段落 → 一键修复并展示
 * before/after 与复检剩余问题。
 *
 * 样式与交互沿用 LatexAuditPanel（中文文案、data-testid、无全局状态）。
 */

import { useCallback, useEffect, useMemo, useState } from 'react';

import { officeApi } from '../../shared/api/officeApi';
import type {
  WordAuditFixResult,
  WordAuditIssue,
  WordAuditResult,
  WordRulePackSummary,
  WordTextAnchor,
} from '../../shared/api/wordAuditTypes';

import { defaultFixedName } from './wordAuditFilename';

const DEFAULT_PACKS: WordRulePackSummary[] = [
  {
    id: 'general-quality',
    name: 'Word 通用质量检查',
    version: '1.0',
    origin: 'builtin',
    rule_count: 6,
  },
  {
    id: 'gb-t-9704-general',
    name: '党政机关公文格式（GB/T 9704 通用参数）',
    version: '1.0',
    origin: 'builtin',
    rule_count: 5,
  },
];
const DEFAULT_PACK_ID = 'general-quality';

type SeverityFilter = 'all' | 'error' | 'warning';

const SEVERITY_CLASS: Record<string, string> = {
  error: 'text-error border-error/40 bg-error/10',
  warning: 'text-warning border-warning/40 bg-warning/10',
};

function anchorLabel(anchor: WordTextAnchor | null | undefined): string | null {
  if (!anchor) return null;
  if (anchor.paragraph_index !== null && anchor.paragraph_index !== undefined) {
    return `第 ${anchor.paragraph_index + 1} 段`;
  }
  if (anchor.table_index !== null && anchor.table_index !== undefined) {
    return `表 ${anchor.table_index + 1}`;
  }
  return null;
}

export interface DocumentAuditPanelProps {
  workspacePath: string;
  filePath: string;
  filename?: string;
  /** 点击 issue 时把锚点交给父级预览滚动/高亮。 */
  onLocate?: (anchor: WordTextAnchor) => void;
  /** overwrite 修复成功后通知父级重新读取文档。 */
  onFixed?: () => void;
}

export function DocumentAuditPanel({
  workspacePath,
  filePath,
  filename,
  onLocate,
  onFixed,
}: DocumentAuditPanelProps) {
  const [packs, setPacks] = useState<WordRulePackSummary[]>([]);
  const [packId, setPackId] = useState(DEFAULT_PACK_ID);
  const [audit, setAudit] = useState<WordAuditResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<SeverityFilter>('all');
  const [overwrite, setOverwrite] = useState(false);
  const [fixing, setFixing] = useState(false);
  const [fixError, setFixError] = useState<string | null>(null);
  const [fixResult, setFixResult] = useState<WordAuditFixResult | null>(null);

  useEffect(() => {
    let cancelled = false;
    void officeApi
      .listWordRulePacks({ workspacePath })
      .then((result) => {
        if (!cancelled && result.ok && result.packs.length > 0) {
          setPacks(result.packs);
        }
      })
      .catch(() => {
        // 列表失败不阻塞审校：默认内置包仍可用
      });
    return () => {
      cancelled = true;
    };
  }, [workspacePath]);

  const runAudit = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await officeApi.auditWord({
        workspace_path: workspacePath,
        file_path: filePath,
        rulepack_id: packId,
      });
      setAudit(result);
      setFixResult(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [workspacePath, filePath, packId]);

  useEffect(() => {
    void runAudit();
  }, [runAudit]);

  const issues = useMemo(() => audit?.issues ?? [], [audit]);
  const visibleIssues = useMemo(
    () => (filter === 'all' ? issues : issues.filter((issue) => issue.severity === filter)),
    [issues, filter],
  );

  const handleFix = async () => {
    if (!audit || fixing) return;
    setFixing(true);
    setFixError(null);
    try {
      const result = await officeApi.fixWord({
        workspace_path: workspacePath,
        file_path: filePath,
        rulepack_id: packId,
        ...(overwrite ? {} : { output_filename: defaultFixedName(filename, filePath) }),
        overwrite,
      });
      setFixResult(result);
      if (overwrite) {
        onFixed?.();
        await runAudit();
      }
    } catch (e: unknown) {
      setFixError(e instanceof Error ? e.message : String(e));
    } finally {
      setFixing(false);
    }
  };

  const issueTotal = audit?.summary.issue_count ?? 0;
  const canFix = Boolean(audit && issueTotal > 0) && !fixing;

  return (
    <section
      className="mt-3 flex flex-col gap-3 rounded border border-border p-4"
      data-testid="word-audit-panel"
    >
      <header className="flex flex-wrap items-start gap-2">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold">Word 规则审校</h3>
          <p className="text-xs text-muted">
            确定性规则包：页面 / 样式 / 结构 / 内容；点击问题可定位到结构化预览段落
          </p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <select
            value={packs.length > 0 ? packId : DEFAULT_PACK_ID}
            onChange={(event) => setPackId(event.target.value)}
            data-testid="word-audit-pack"
            aria-label="规则包"
            className="rounded border border-border bg-surface px-2 py-1 text-xs"
          >
            {(packs.length > 0 ? packs : DEFAULT_PACKS).map((pack) => (
              <option key={pack.id} value={pack.id}>
                {pack.name}
                {pack.origin === 'workspace' ? '（工作区）' : ''}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => void runAudit()}
            disabled={loading}
            data-testid="word-audit-run"
            className="rounded border border-border px-2 py-1 text-xs text-text-secondary hover:bg-bg-hover disabled:opacity-50"
          >
            {loading ? '审校中…' : '重新审校'}
          </button>
          <button
            type="button"
            onClick={() => void handleFix()}
            disabled={!canFix}
            data-testid="word-audit-fix"
            className="rounded border border-primary/40 bg-primary/10 px-2 py-1 text-xs text-primary hover:bg-primary/20 disabled:opacity-50"
          >
            {fixing ? '修复中…' : '一键修复'}
          </button>
          <label className="flex items-center gap-1 text-xs text-muted">
            <input
              type="checkbox"
              checked={overwrite}
              onChange={(event) => setOverwrite(event.target.checked)}
              data-testid="word-audit-overwrite"
            />
            覆盖原文件
          </label>
        </div>
      </header>

      {error && (
        <p className="text-xs text-error" data-testid="word-audit-error">
          {error}
        </p>
      )}

      {audit && (
        <>
          <div
            className="flex flex-wrap items-center gap-2 text-xs"
            data-testid="word-audit-summary"
          >
            <span className={audit.ok ? 'text-success' : 'text-error'}>
              {audit.ok ? '通过' : '存在错误'}
            </span>
            <span className="text-muted">
              检查 {audit.summary.rules_checked} 条规则 · {audit.summary.error_count} 错误 ·{' '}
              {audit.summary.warning_count} 警告
            </span>
            <span className="text-muted">{audit.rule_pack_id}</span>
          </div>

          <div className="flex items-center gap-2 text-xs">
            {(
              [
                ['all', `全部 ${issueTotal}`],
                ['error', `错误 ${audit.summary.error_count}`],
                ['warning', `警告 ${audit.summary.warning_count}`],
              ] as [SeverityFilter, string][]
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => setFilter(value)}
                data-testid={`word-audit-filter-${value}`}
                className={`rounded border px-2 py-0.5 ${
                  filter === value
                    ? 'border-primary text-primary bg-primary/10'
                    : 'border-border text-text-secondary hover:bg-bg-hover'
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {visibleIssues.length === 0 ? (
            <p className="text-xs text-muted" data-testid="word-audit-empty">
              {issueTotal === 0 ? '未发现问题。' : '当前筛选下没有问题。'}
            </p>
          ) : (
            <ul className="flex flex-col gap-2" data-testid="word-audit-issues">
              {visibleIssues.map((issue, index) => (
                <li key={`${issue.rule_id}-${index}`}>
                  <IssueCard issue={issue} onLocate={onLocate} index={index} />
                </li>
              ))}
            </ul>
          )}

          {audit.warnings.length > 0 && (
            <ul className="text-xs text-muted" data-testid="word-audit-warnings">
              {audit.warnings.map((warning, index) => (
                <li key={`${warning.code}-${index}`}>
                  {warning.code}: {warning.message}
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      {fixError && (
        <p className="text-xs text-error" data-testid="word-audit-fix-error">
          {fixError}
        </p>
      )}

      {fixResult && (
        <div
          className="rounded border border-border bg-bg-subtle p-3 text-xs"
          data-testid="word-audit-fix-result"
        >
          <p>
            已应用 {fixResult.fixed_count} 项修复
            {fixResult.overwritten ? '（已覆盖原文件）' : `，输出 ${fixResult.output_path}`}
          </p>
          <p>
            复检：{fixResult.remaining.summary.error_count} 错误 ·{' '}
            {fixResult.remaining.summary.warning_count} 警告
          </p>
          {fixResult.actions.length > 0 && (
            <ul className="mt-1 text-muted">
              {fixResult.actions.map((action) => (
                <li key={action.rule_id}>
                  {action.rule_id} × {action.fixed_count}
                </li>
              ))}
            </ul>
          )}
          {fixResult.warnings.length > 0 && (
            <ul className="mt-1 text-muted">
              {fixResult.warnings.map((warning, index) => (
                <li key={`${warning.code}-${index}`}>
                  {warning.code}: {warning.message}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}

function IssueCard({
  issue,
  onLocate,
  index,
}: {
  issue: WordAuditIssue;
  onLocate?: (anchor: WordTextAnchor) => void;
  index: number;
}) {
  const label = anchorLabel(issue.anchor);
  const content = (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`rounded border px-1.5 py-0.5 text-ui-2xs ${
            SEVERITY_CLASS[issue.severity] ?? 'text-muted border-border bg-bg-subtle'
          }`}
        >
          {issue.severity === 'error' ? '错误' : '警告'}
        </span>
        <code className="text-ui-2xs text-text-secondary">{issue.rule_id}</code>
        {label && <span className="text-ui-2xs text-primary">定位 {label}</span>}
      </div>
      <p className="mt-1 text-sm text-text">{issue.message}</p>
      {(issue.expected || issue.actual) && (
        <p className="mt-0.5 text-xs text-muted">
          期望 {issue.expected ?? '-'} · 实测 {issue.actual ?? '-'}
        </p>
      )}
      {issue.fix_hint && <p className="mt-0.5 text-xs text-muted">{issue.fix_hint}</p>}
      {issue.source && <p className="mt-0.5 text-ui-2xs text-muted">{issue.source}</p>}
    </>
  );

  if (issue.anchor && onLocate) {
    return (
      <button
        type="button"
        onClick={() => onLocate(issue.anchor as WordTextAnchor)}
        data-testid={`word-audit-issue-${index}`}
        className="w-full rounded border border-border p-2 text-left hover:bg-bg-hover"
      >
        {content}
      </button>
    );
  }
  return (
    <div data-testid={`word-audit-issue-${index}`} className="rounded border border-border p-2">
      {content}
    </div>
  );
}
