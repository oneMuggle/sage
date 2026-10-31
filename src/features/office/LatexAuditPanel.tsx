import { useState } from 'react';

import { auditLatex, type LatexAuditResult } from '../../shared/api/latexApi';
import { useCurrentWorkspace } from '../../shared/lib/workspaceContext';

import { LatexPathPicker } from './LatexPathPicker';
import { joinWorkspacePath } from './latexPath';

function splitSections(value: string): string[] {
  return value
    .split(/[,，;；]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

const SEVERITY_CLASS: Record<string, string> = {
  error: 'text-error border-error/40 bg-error/10',
  warning: 'text-warning border-warning/40 bg-warning/10',
  info: 'text-muted border-border bg-bg-subtle',
};

export interface LatexAuditPanelProps {
  workspacePath?: string | null;
}

export function LatexAuditPanel({ workspacePath: wsOverride }: LatexAuditPanelProps) {
  const activeWorkspace = useCurrentWorkspace() ?? null;
  const workspacePath = wsOverride ?? activeWorkspace;

  const [filePath, setFilePath] = useState('');
  const [sections, setSections] = useState('');
  const [result, setResult] = useState<LatexAuditResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canUse = Boolean(workspacePath && workspacePath.trim());

  const handleAudit = async () => {
    if (!canUse || !filePath.trim()) {
      setError('请先绑定工作区并填写 .tex 路径');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const data = await auditLatex(
        workspacePath!,
        joinWorkspacePath(workspacePath!, filePath),
        splitSections(sections),
      );
      setResult(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      className="flex flex-col gap-3 rounded border border-border p-4"
      data-testid="latex-audit-panel"
    >
      <header>
        <h2 className="text-base font-semibold">LaTeX 源码审校</h2>
        <p className="text-xs text-muted">
          确定性检查：documentclass/title/author/abstract、引用/交叉引用、图表题注、TODO、危险命令与
          include 越界；不编译 TeX
        </p>
      </header>

      <div className="flex gap-2">
        <LatexPathPicker
          value={filePath}
          onChange={setFilePath}
          title="选择 LaTeX 源码"
          extensions={['tex', 'ltx']}
          placeholder="paper/main.tex"
          testId="latex-audit-path"
          className="flex-1"
        />
        <button
          type="button"
          className="rounded border border-border px-3 py-1 text-sm hover:bg-bg-hover disabled:opacity-50"
          onClick={handleAudit}
          disabled={busy}
          data-testid="latex-audit-run"
        >
          {busy ? '审校中…' : '开始审校'}
        </button>
      </div>

      <input
        className="rounded border border-border bg-bg px-2 py-1 text-sm"
        placeholder="必需章节（可选，逗号分隔）：Introduction, Conclusion"
        value={sections}
        onChange={(event) => setSections(event.target.value)}
        data-testid="latex-audit-sections"
      />

      {error ? <div className="text-sm text-error">{error}</div> : null}

      {result ? (
        <div className="flex flex-col gap-2" data-testid="latex-audit-result">
          <div className="text-xs text-muted">
            {result.source_path} · {result.summary.count} issues · error{' '}
            {result.summary.severity.error} / warning {result.summary.severity.warning}
          </div>
          {result.issues.length === 0 ? (
            <div className="text-sm text-success">未发现源码级问题</div>
          ) : (
            <ul className="flex flex-col gap-2">
              {result.issues.map((issue, index) => (
                <li
                  key={`${issue.rule_id}-${index}`}
                  className={`rounded border px-3 py-2 text-sm ${
                    SEVERITY_CLASS[issue.severity] ?? SEVERITY_CLASS.info
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs">{issue.rule_id}</span>
                    <span className="text-xs uppercase">{issue.severity}</span>
                    {issue.anchor ? (
                      <span className="text-xs text-muted">
                        {issue.anchor.file}:{issue.anchor.line}
                      </span>
                    ) : null}
                  </div>
                  <div className="mt-1">{issue.message}</div>
                  {issue.fix_hint ? (
                    <div className="text-xs text-muted mt-1">建议：{issue.fix_hint}</div>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </section>
  );
}
