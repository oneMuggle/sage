/**
 * OfficeAiAssistantPanel (M3) — 规范书 + LLM 合并审校面板。
 *
 * 选择 Word 文档后跑一次审校：先执行规范书确定性规则，再由 LLM 补充
 * 语义建议；结果按严重度 + 来源（规范书 / AI 补充 / 内置规则）展示，
 * 并可按来源过滤。副栏可查看该文档的历史审校记录。
 *
 * 与 OfficeSpecLibrary 相邻挂载在「规则与审校」Tab。
 */

import { useCallback, useEffect, useMemo, useState } from 'react';

import { officeApi } from '../../shared/api/officeApi';
import { officeSpecApi } from '../../shared/api/officeSpecApi';
import type {
  AiReviewHistoryItem,
  AiReviewIssue,
  AiReviewResult,
  AiReviewSeverity,
  AiReviseResult,
  OfficeSpecDocument,
} from '../../shared/api/officeSpecTypes';

import { LatexPathPicker } from './LatexPathPicker';
import { joinWorkspacePath } from './latexPath';

const REVIEW_EXTENSIONS = ['docx'];

const SEVERITY_LABEL: Record<AiReviewSeverity, string> = {
  error: '错误',
  warning: '警告',
  info: '提示',
};

const SEVERITY_CLASS: Record<AiReviewSeverity, string> = {
  error: 'bg-error/10 text-error',
  warning: 'bg-warning/10 text-warning',
  info: 'bg-primary/10 text-primary',
};

type SourceFilter = 'all' | 'spec' | 'llm';

function formatTimestamp(value: number): string {
  if (!value) return '—';
  return new Date(value).toLocaleString('zh-CN', { hour12: false });
}

function sourceLabel(issue: AiReviewIssue): string {
  if (issue.source.kind === 'spec') {
    return issue.source.spec_name ? `规范书 · ${issue.source.spec_name}` : '规范书';
  }
  if (issue.source.kind === 'llm') return 'AI 补充';
  return '内置规则';
}

export interface OfficeAiAssistantPanelProps {
  workspacePath?: string | null;
}

export function OfficeAiAssistantPanel({ workspacePath }: OfficeAiAssistantPanelProps) {
  const [filePath, setFilePath] = useState('');
  const [docId, setDocId] = useState('');
  const [specId, setSpecId] = useState('');
  const [useLlm, setUseLlm] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AiReviewResult | null>(null);
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all');

  const [specs, setSpecs] = useState<OfficeSpecDocument[]>([]);
  const [specListError, setSpecListError] = useState<string | null>(null);

  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [historyRuns, setHistoryRuns] = useState<AiReviewHistoryItem[] | null>(null);

  // T6: 应用到文档（修订痕迹应用 + 自动快照）
  const [selectedIssues, setSelectedIssues] = useState<Set<string>>(new Set());
  const [revising, setRevising] = useState(false);
  const [reviseResult, setReviseResult] = useState<AiReviseResult | null>(null);
  const [reviseError, setReviseError] = useState<string | null>(null);
  const [showConfirmDialog, setShowConfirmDialog] = useState(false);

  const canUse = Boolean(workspacePath && workspacePath.trim());

  useEffect(() => {
    if (!workspacePath) {
      setSpecs([]);
      return;
    }
    let cancelled = false;
    setSpecListError(null);
    officeApi
      .listSpecs({ workspacePath })
      .then((list) => {
        if (!cancelled) setSpecs(list.specs);
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setSpecs([]);
          setSpecListError(e instanceof Error ? e.message : String(e));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [workspacePath]);

  const handleRun = async () => {
    if (!workspacePath) return;
    if (!filePath.trim()) {
      setError('请先选择要审校的 Word 文档');
      return;
    }
    setRunning(true);
    setError(null);
    setResult(null);
    setHistoryRuns(null);
    setHistoryError(null);
    try {
      const review = await officeApi.runAiReview({
        workspace_path: workspacePath,
        file_path: joinWorkspacePath(workspacePath, filePath),
        ...(docId.trim() ? { doc_id: docId.trim() } : {}),
        ...(specId ? { spec_id: specId } : {}),
        scope: 'full',
        use_llm: useLlm,
      });
      setResult(review);
      setSourceFilter('all');
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  const handleToggleIssue = (issueId: string) => {
    setSelectedIssues((prev) => {
      const next = new Set(prev);
      if (next.has(issueId)) {
        next.delete(issueId);
      } else {
        next.add(issueId);
      }
      return next;
    });
  };

  const handleSelectAllIssues = () => {
    if (selectedIssues.size === selectableIssues.length && selectableIssues.length > 0) {
      setSelectedIssues(new Set());
    } else {
      setSelectedIssues(new Set(selectableIssues.map((i) => i.id)));
    }
  };

  const handleApplyRevisions = async () => {
    if (!workspacePath || !filePath.trim() || selectedIssues.size === 0) return;
    const issuesToApply = selectableIssues.filter((i) => selectedIssues.has(i.id));
    if (issuesToApply.length === 0) return;

    setRevising(true);
    setReviseError(null);
    setReviseResult(null);
    setShowConfirmDialog(false);
    try {
      const result = await officeSpecApi.reviseAiIssues({
        workspace_path: workspacePath,
        file_path: joinWorkspacePath(workspacePath, filePath),
        ...(docId.trim() ? { doc_id: docId.trim() } : {}),
        issues: issuesToApply,
        add_comments: true,
      });
      setReviseResult(result);
      setSelectedIssues(new Set());
    } catch (e: unknown) {
      setReviseError(e instanceof Error ? e.message : String(e));
    } finally {
      setRevising(false);
    }
  };

  const loadHistory = useCallback(async () => {
    if (!workspacePath) return;
    if (!docId.trim()) {
      setHistoryError('请先填写文档 ID 再查看历史');
      return;
    }
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const history = await officeApi.listAiReviews(docId.trim(), {
        workspacePath,
        limit: 10,
      });
      setHistoryRuns(history.runs);
    } catch (e: unknown) {
      setHistoryError(e instanceof Error ? e.message : String(e));
    } finally {
      setHistoryLoading(false);
    }
  }, [workspacePath, docId]);

  const filteredIssues = useMemo(() => {
    if (!result) return [];
    if (sourceFilter === 'all') return result.issues;
    return result.issues.filter((issue) => issue.source.kind === sourceFilter);
  }, [result, sourceFilter]);

  const selectableIssues = useMemo(
    () => filteredIssues.filter((i) => i.fixable && i.actual && (i.expected || i.suggestion)),
    [filteredIssues],
  );

  const summary = result?.summary;

  return (
    <section
      className="rounded-lg border border-border bg-bg-subtle p-4 flex flex-col gap-3"
      data-testid="office-ai-assistant"
    >
      <div>
        <h2 className="text-base font-medium text-text">AI 审校</h2>
        <p className="text-xs text-muted mt-1">
          先按当前生效的格式规范书检查排版与结构，再由 AI 补充语义层面的建议。
          规范书可在上方「格式规范书库」中维护。
        </p>
      </div>

      {!canUse ? (
        <p className="text-xs text-muted" data-testid="office-ai-no-workspace">
          请先在上方绑定工作区，再运行 AI 审校。
        </p>
      ) : (
        <>
          {error ? (
            <p className="text-xs text-error" data-testid="office-ai-error">
              {error}
            </p>
          ) : null}

          <div className="flex flex-col gap-2" data-testid="office-ai-controls">
            <LatexPathPicker
              value={filePath}
              onChange={setFilePath}
              title="选择 Word 文档"
              extensions={REVIEW_EXTENSIONS}
              placeholder="例如 docs/draft.docx（相对工作区或绝对路径）"
              testId="office-ai-path"
            />
            <div className="flex flex-wrap items-center gap-2">
              <input
                className="min-w-40 flex-1 rounded border border-border bg-bg px-2 py-1 text-sm"
                placeholder="文档 ID（可选，用于记录历史与文档级绑定）"
                value={docId}
                onChange={(event) => setDocId(event.target.value)}
                data-testid="office-ai-doc-id"
              />
              <select
                className="min-w-40 flex-1 rounded border border-border bg-bg px-2 py-1 text-sm"
                value={specId}
                onChange={(event) => setSpecId(event.target.value)}
                data-testid="office-ai-spec-id"
              >
                <option value="">（自动：文档绑定 / 工作区默认）</option>
                {specs.map((spec) => (
                  <option key={spec.id} value={spec.id}>
                    {spec.name}
                    {spec.is_default ? '（默认）' : ''}
                  </option>
                ))}
              </select>
              <label className="flex items-center gap-1 text-xs text-text-secondary">
                <input
                  type="checkbox"
                  checked={useLlm}
                  onChange={(event) => setUseLlm(event.target.checked)}
                  data-testid="office-ai-use-llm"
                />
                启用 AI 补充
              </label>
              <button
                type="button"
                onClick={() => void handleRun()}
                disabled={running}
                className="px-3 py-1.5 rounded bg-primary text-text-inverse text-sm hover:bg-primary-hover disabled:opacity-50"
                data-testid="office-ai-run"
              >
                {running ? '审校中…' : '开始审校'}
              </button>
            </div>
            {specListError ? (
              <p className="text-xs text-muted" data-testid="office-ai-spec-list-error">
                规范书列表加载失败：{specListError}
              </p>
            ) : null}
          </div>

          {result ? (
            <div className="flex flex-col gap-3" data-testid="office-ai-result">
              <div
                className="rounded border border-border bg-bg px-3 py-2 text-xs text-text-secondary flex flex-wrap items-center gap-x-4 gap-y-1"
                data-testid="office-ai-summary"
              >
                <span data-testid="office-ai-current-spec">
                  当前规范书：
                  {result.spec_name ?? '未绑定（仅内置规则）'}
                </span>
                <span>检查规则 {summary?.rules_checked ?? 0} 条</span>
                <span data-testid="office-ai-issue-count">
                  问题 {summary?.issue_count ?? 0} 个（错误 {summary?.error_count ?? 0} / 警告{' '}
                  {summary?.warning_count ?? 0} / 提示 {summary?.info_count ?? 0}）
                </span>
                <span>
                  规范书 {summary?.spec_issue_count ?? 0} · AI 补充 {summary?.llm_issue_count ?? 0}
                </span>
                <span>耗时 {summary?.duration_ms ?? 0} ms</span>
                {summary?.model ? <span>模型 {summary.model}</span> : null}
              </div>

              {result.warnings.length > 0 ? (
                <ul
                  className="rounded border border-warning/40 bg-warning/5 px-3 py-2 text-xs text-text-secondary flex flex-col gap-1"
                  data-testid="office-ai-warnings"
                >
                  {result.warnings.map((warning, index) => (
                    <li key={`${warning.code}-${index}`}>
                      {warning.code}
                      {warning.message ? `：${warning.message}` : ''}
                    </li>
                  ))}
                </ul>
              ) : null}

              <div className="flex items-center gap-2" data-testid="office-ai-filters">
                {(
                  [
                    ['all', '全部'],
                    ['spec', '规范书规则'],
                    ['llm', 'AI 补充'],
                  ] as const
                ).map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setSourceFilter(key)}
                    className={`px-2 py-1 rounded border text-xs ${
                      sourceFilter === key
                        ? 'border-primary text-primary bg-primary/10'
                        : 'border-border text-text-secondary hover:bg-bg-hover'
                    }`}
                    data-testid={`office-ai-filter-${key}`}
                  >
                    {label}
                  </button>
                ))}
                {selectableIssues.length > 0 ? (
                  <label className="flex items-center gap-1 text-xs text-text-secondary ml-auto">
                    <input
                      type="checkbox"
                      checked={
                        selectedIssues.size > 0 && selectedIssues.size === selectableIssues.length
                      }
                      onChange={() => handleSelectAllIssues()}
                      data-testid="office-ai-select-all"
                    />
                    全选
                  </label>
                ) : null}
              </div>

              {selectedIssues.size > 0 ? (
                <div className="flex items-center gap-2" data-testid="office-ai-apply-bar">
                  <button
                    type="button"
                    onClick={() => setShowConfirmDialog(true)}
                    disabled={revising}
                    className="px-3 py-1.5 rounded bg-primary text-text-inverse text-sm hover:bg-primary-hover disabled:opacity-50"
                    data-testid="office-ai-apply-button"
                  >
                    应用到文档（{selectedIssues.size} 个问题）
                  </button>
                  <button
                    type="button"
                    onClick={() => setSelectedIssues(new Set())}
                    className="px-2 py-1 rounded border border-border text-xs text-text-secondary hover:bg-bg-hover"
                    data-testid="office-ai-clear-selection"
                  >
                    清除选择
                  </button>
                </div>
              ) : null}

              {filteredIssues.length === 0 ? (
                <p className="text-xs text-muted" data-testid="office-ai-empty">
                  {result.issues.length === 0 ? '未发现问题。' : '当前筛选下没有问题。'}
                </p>
              ) : (
                <ul className="flex flex-col gap-2" data-testid="office-ai-issues">
                  {filteredIssues.map((issue) => (
                    <li
                      key={issue.id}
                      className="rounded border border-border bg-bg px-3 py-2 flex flex-col gap-1"
                      data-testid={`office-ai-issue-${issue.id}`}
                    >
                      <div className="flex items-start gap-2">
                        <input
                          type="checkbox"
                          checked={selectedIssues.has(issue.id)}
                          onChange={() => handleToggleIssue(issue.id)}
                          disabled={
                            !issue.fixable ||
                            !issue.actual ||
                            (!issue.expected && !issue.suggestion)
                          }
                          className="mt-1"
                          data-testid={`office-ai-issue-checkbox-${issue.id}`}
                        />
                        <div className="flex-1 flex flex-col gap-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <span
                              className={`px-1.5 py-0.5 rounded text-xs ${SEVERITY_CLASS[issue.severity]}`}
                            >
                              {SEVERITY_LABEL[issue.severity]}
                            </span>
                            <span
                              className="px-1.5 py-0.5 rounded bg-bg-hover text-text-secondary text-xs"
                              data-testid={`office-ai-issue-source-${issue.id}`}
                            >
                              {sourceLabel(issue)}
                            </span>
                            <span className="text-xs text-muted">{issue.category}</span>
                            {!issue.fixable ? (
                              <span className="text-xs text-muted">（不可自动修复）</span>
                            ) : null}
                          </div>
                          <p className="text-sm text-text">{issue.message}</p>
                          {issue.actual || issue.expected ? (
                            <div className="text-xs text-text-secondary flex flex-col gap-0.5">
                              {issue.actual ? (
                                <p>
                                  <span className="text-muted">原文：</span>
                                  <span className="bg-error/10 px-1 rounded">{issue.actual}</span>
                                </p>
                              ) : null}
                              {issue.expected ? (
                                <p>
                                  <span className="text-muted">修改为：</span>
                                  <span className="bg-success/10 px-1 rounded">
                                    {issue.expected}
                                  </span>
                                </p>
                              ) : issue.suggestion ? (
                                <p>
                                  <span className="text-muted">建议：</span>
                                  <span className="bg-success/10 px-1 rounded">
                                    {issue.suggestion}
                                  </span>
                                </p>
                              ) : null}
                            </div>
                          ) : issue.suggestion ? (
                            <p className="text-xs text-text-secondary">建议：{issue.suggestion}</p>
                          ) : null}
                          {issue.rationale ? (
                            <p className="text-xs text-muted">依据：{issue.rationale}</p>
                          ) : null}
                          {issue.location?.paragraph_text ? (
                            <p className="text-xs text-muted truncate">
                              段落 {issue.location.paragraph_index ?? '—'}：
                              {issue.location.paragraph_text}
                            </p>
                          ) : null}
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}

              {reviseError ? (
                <p className="text-xs text-error" data-testid="office-ai-revise-error">
                  应用修订失败：{reviseError}
                </p>
              ) : null}

              {reviseResult ? (
                <div
                  className="rounded border border-success/40 bg-success/5 px-3 py-2 text-xs text-text-secondary flex flex-col gap-1"
                  data-testid="office-ai-revise-result"
                >
                  <p className="text-text font-medium">
                    ✓ 已应用 {reviseResult.applied} 个修订
                    {reviseResult.skipped > 0 ? `（跳过 ${reviseResult.skipped} 个）` : ''}
                  </p>
                  {reviseResult.snapshot_path ? (
                    <p>
                      快照已保存：
                      <span className="text-muted font-mono text-ui-2xs">
                        {reviseResult.snapshot_path}
                      </span>
                    </p>
                  ) : null}
                  <p>
                    输出文件：
                    <span className="text-muted font-mono text-ui-2xs">
                      {reviseResult.output_path}
                    </span>
                    {reviseResult.overwritten ? '（已覆盖原文件）' : ''}
                  </p>
                </div>
              ) : null}

              {showConfirmDialog ? (
                <div
                  className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
                  data-testid="office-ai-confirm-dialog"
                >
                  <div className="bg-bg border border-border rounded-lg shadow-lg max-w-2xl w-full mx-4 max-h-[80vh] flex flex-col">
                    <div className="px-4 py-3 border-b border-border flex items-center justify-between">
                      <h3 className="text-base font-medium text-text">确认应用修订</h3>
                      <button
                        type="button"
                        onClick={() => setShowConfirmDialog(false)}
                        className="text-muted hover:text-text"
                        data-testid="office-ai-confirm-cancel-top"
                      >
                        ✕
                      </button>
                    </div>
                    <div className="px-4 py-3 flex-1 overflow-auto">
                      <p className="text-sm text-text-secondary mb-3">
                        将对以下 {selectedIssues.size} 个问题应用 Word 修订痕迹（
                        <code className="text-xs bg-bg-hover px-1 rounded">w:ins</code> /{' '}
                        <code className="text-xs bg-bg-hover px-1 rounded">w:del</code>）：
                      </p>
                      <ul className="flex flex-col gap-2">
                        {filteredIssues
                          .filter((i) => selectedIssues.has(i.id))
                          .map((issue) => (
                            <li
                              key={issue.id}
                              className="text-xs border border-border rounded px-2 py-1.5"
                            >
                              <p className="text-text">{issue.message}</p>
                              {issue.actual && issue.expected ? (
                                <p className="text-text-secondary mt-1">
                                  <span className="bg-error/10 px-1 rounded">{issue.actual}</span>
                                  {' → '}
                                  <span className="bg-success/10 px-1 rounded">
                                    {issue.expected}
                                  </span>
                                </p>
                              ) : null}
                            </li>
                          ))}
                      </ul>
                      <p className="text-xs text-muted mt-3">
                        应用前会自动创建快照（若文档 ID 已登记），可在右侧面板查看并恢复。
                      </p>
                    </div>
                    <div className="px-4 py-3 border-t border-border flex items-center justify-end gap-2">
                      <button
                        type="button"
                        onClick={() => setShowConfirmDialog(false)}
                        className="px-3 py-1.5 rounded border border-border text-sm text-text-secondary hover:bg-bg-hover"
                        data-testid="office-ai-confirm-cancel"
                      >
                        取消
                      </button>
                      <button
                        type="button"
                        onClick={() => void handleApplyRevisions()}
                        disabled={revising}
                        className="px-3 py-1.5 rounded bg-primary text-text-inverse text-sm hover:bg-primary-hover disabled:opacity-50"
                        data-testid="office-ai-confirm-apply"
                      >
                        {revising ? '应用中…' : '确认应用'}
                      </button>
                    </div>
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}

          <div
            className="border-t border-border pt-3 flex flex-col gap-2"
            data-testid="office-ai-history"
          >
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-text">审校历史</span>
              <span className="text-xs text-muted">（使用上方文档 ID）</span>
              <button
                type="button"
                onClick={() => void loadHistory()}
                disabled={historyLoading}
                className="px-2 py-1 rounded border border-border text-xs text-text-secondary hover:bg-bg-hover disabled:opacity-50"
                data-testid="office-ai-history-load"
              >
                {historyLoading ? '加载中…' : '查看历史'}
              </button>
            </div>
            {historyError ? (
              <p className="text-xs text-error" data-testid="office-ai-history-error">
                {historyError}
              </p>
            ) : null}
            {historyRuns ? (
              historyRuns.length === 0 ? (
                <p className="text-xs text-muted" data-testid="office-ai-history-empty">
                  暂无审校历史。
                </p>
              ) : (
                <ul className="flex flex-col divide-y divide-border rounded border border-border bg-bg">
                  {historyRuns.map((run) => (
                    <li
                      key={run.id}
                      className="px-3 py-2 text-xs text-text-secondary flex flex-wrap items-center gap-x-4 gap-y-1"
                      data-testid={`office-ai-history-${run.id}`}
                    >
                      <span>{formatTimestamp(run.created_at)}</span>
                      <span>问题 {run.issue_count} 个</span>
                      <span>{run.scope}</span>
                      {run.model ? <span>{run.model}</span> : null}
                      {run.duration_ms ? <span>{run.duration_ms} ms</span> : null}
                    </li>
                  ))}
                </ul>
              )
            ) : null}
          </div>
        </>
      )}
    </section>
  );
}
