import { useState } from 'react';

import {
  analyzeLatexTemplate,
  fillLatexTemplate,
  type LatexFillResult,
  type LatexTemplateProfile,
  type LatexTemplateSlot,
} from '../../shared/api/latexApi';
import { useCurrentWorkspace } from '../../shared/lib/workspaceContext';

function joinWorkspacePath(root: string, relative: string): string {
  const rel = relative.trim().replace(/^[\\/]+/, '');
  if (!rel) return '';
  if (/^([a-zA-Z]:[\\/]|[\\/])/.test(rel)) return rel;
  const separator = root.includes('\\') ? '\\' : '/';
  return `${root.replace(/[\\/]+$/, '')}${separator}${rel}`;
}

function defaultValue(slot: LatexTemplateSlot): string {
  if (slot.type === 'list') {
    return slot.current_value
      .split(/\s*(?:,|，|;|；|\\and)\s*/)
      .filter(Boolean)
      .join(', ');
  }
  return slot.current_value;
}

function toDataValue(slot: LatexTemplateSlot, raw: string): string | string[] {
  if (slot.type === 'list') {
    return raw
      .split(/\s*(?:,|，|;|；)\s*/)
      .map((item) => item.trim())
      .filter(Boolean);
  }
  return raw;
}

function defaultOutputName(templatePath: string): string {
  const name = templatePath.split(/[\\/]/).pop() || 'template.tex';
  return name.replace(/\.(tex|ltx)$/i, '') + '-filled.tex';
}

export interface LatexTemplatePanelProps {
  /** Optional override; falls back to the active session workspace. */
  workspacePath?: string | null;
}

export function LatexTemplatePanel({ workspacePath: wsOverride }: LatexTemplatePanelProps) {
  const activeWorkspace = useCurrentWorkspace() ?? null;
  const workspacePath = wsOverride ?? activeWorkspace;

  const [templatePath, setTemplatePath] = useState('');
  const [profile, setProfile] = useState<LatexTemplateProfile | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [outputName, setOutputName] = useState('');
  const [fillResult, setFillResult] = useState<LatexFillResult | null>(null);
  const [busy, setBusy] = useState<'analyze' | 'fill' | null>(null);
  const [error, setError] = useState<string | null>(null);

  const canUse = Boolean(workspacePath && workspacePath.trim());

  const handleAnalyze = async () => {
    if (!canUse || !templatePath.trim()) {
      setError('请先绑定工作区并填写模板路径');
      return;
    }
    setBusy('analyze');
    setError(null);
    setFillResult(null);
    try {
      const result = await analyzeLatexTemplate(
        workspacePath!,
        joinWorkspacePath(workspacePath!, templatePath),
      );
      setProfile(result);
      setValues(
        Object.fromEntries(result.slots.map((slot) => [slot.name, defaultValue(slot)])),
      );
      setOutputName(defaultOutputName(templatePath));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const handleFill = async () => {
    if (!canUse || !profile) return;
    setBusy('fill');
    setError(null);
    try {
      const data = Object.fromEntries(
        profile.slots.map((slot) => [
          slot.name,
          toDataValue(slot, values[slot.name] ?? ''),
        ]),
      );
      const result = await fillLatexTemplate(
        workspacePath!,
        joinWorkspacePath(workspacePath!, templatePath),
        outputName,
        data,
      );
      setFillResult(result);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <section
      className="flex flex-col gap-3 rounded border border-border p-4"
      data-testid="latex-template-panel"
    >
      <header>
        <h2 className="text-base font-semibold">LaTeX 模板助手</h2>
        <p className="text-xs text-muted">
          输入工作区内的 .tex 模板路径 → 分析槽位 → 填写并输出新的 .tex（不覆盖模板，不编译 TeX）
        </p>
      </header>

      <div className="flex gap-2">
        <input
          className="flex-1 rounded border border-border bg-bg px-2 py-1 text-sm"
          placeholder="paper/main.tex"
          value={templatePath}
          onChange={(event) => setTemplatePath(event.target.value)}
          data-testid="latex-template-path"
        />
        <button
          type="button"
          className="rounded border border-border px-3 py-1 text-sm hover:bg-bg-hover disabled:opacity-50"
          onClick={handleAnalyze}
          disabled={busy !== null}
          data-testid="latex-template-analyze"
        >
          {busy === 'analyze' ? '分析中…' : '分析模板'}
        </button>
      </div>

      {error ? <div className="text-sm text-error">{error}</div> : null}

      {profile ? (
        <div className="flex flex-col gap-2">
          <div className="text-xs text-muted">
            {profile.document_class ?? 'unknown class'} · {profile.slots.length} slots ·{' '}
            {profile.packages.length} packages
            {profile.warnings.length > 0 ? ` · ${profile.warnings.length} warnings` : ''}
          </div>

          {profile.slots.map((slot) => (
            <label key={slot.name} className="flex flex-col gap-1 text-sm">
              <span className="flex items-center gap-2">
                <span className="font-mono text-xs text-muted">{slot.name}</span>
                {slot.required ? <span className="text-error text-xs">*</span> : null}
                <span className="text-xs text-muted">{slot.description}</span>
              </span>
              {slot.type === 'rich_text' || slot.kind === 'environment_body' ? (
                <textarea
                  className="min-h-[5rem] rounded border border-border bg-bg px-2 py-1 text-sm"
                  value={values[slot.name] ?? ''}
                  onChange={(event) =>
                    setValues((current) => ({ ...current, [slot.name]: event.target.value }))
                  }
                  data-testid={`latex-slot-${slot.name}`}
                />
              ) : (
                <input
                  className="rounded border border-border bg-bg px-2 py-1 text-sm"
                  value={values[slot.name] ?? ''}
                  onChange={(event) =>
                    setValues((current) => ({ ...current, [slot.name]: event.target.value }))
                  }
                  data-testid={`latex-slot-${slot.name}`}
                />
              )}
              <span className="text-xs text-muted">
                当前值：{slot.current_value || '（空）'}
                {slot.type === 'list' ? ' · 多个值用逗号分隔' : ''}
              </span>
            </label>
          ))}

          <div className="flex gap-2">
            <input
              className="flex-1 rounded border border-border bg-bg px-2 py-1 text-sm"
              placeholder="输出文件名，如 main-filled.tex"
              value={outputName}
              onChange={(event) => setOutputName(event.target.value)}
              data-testid="latex-template-output"
            />
            <button
              type="button"
              className="rounded bg-accent px-3 py-1 text-sm text-white hover:opacity-90 disabled:opacity-50"
              onClick={handleFill}
              disabled={busy !== null || !outputName.trim()}
              data-testid="latex-template-fill"
            >
              {busy === 'fill' ? '填充中…' : '填充并输出'}
            </button>
          </div>
        </div>
      ) : null}

      {fillResult ? (
        <div
          className="rounded border border-success/40 bg-success/10 p-3 text-sm"
          data-testid="latex-fill-result"
        >
          <div className="font-medium">
            已生成 {fillResult.output_path}（{fillResult.filled_count} 个槽位）
          </div>
          {fillResult.unfilled_slots.length > 0 ? (
            <div className="text-xs text-muted mt-1">
              未填：{fillResult.unfilled_slots.join(', ')}
            </div>
          ) : null}
          {fillResult.validation.issues.length > 0 ? (
            <ul className="mt-1 text-xs text-warning list-disc pl-4">
              {fillResult.validation.issues.map((issue, index) => (
                <li key={`${issue.code}-${index}`}>
                  {issue.message}（line {issue.line}）
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
