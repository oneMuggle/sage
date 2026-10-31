import { useEffect, useState } from 'react';

import {
  compileLatex,
  getLatexCapabilities,
  latexdiff,
  type LatexCapabilities,
  type LatexCompileResult,
  type LatexDiffResult,
} from '../../shared/api/latexApi';
import { useCurrentWorkspace } from '../../shared/lib/workspaceContext';

import { joinWorkspacePath } from './latexPath';

function ResultBox({
  title,
  result,
}: {
  title: string;
  result: LatexCompileResult | LatexDiffResult;
}) {
  const path = result.ok
    ? 'pdf_path' in result
      ? result.pdf_path
      : 'diff_path' in result
        ? result.diff_path
        : undefined
    : undefined;
  return (
    <div
      className="rounded border border-border bg-bg-subtle p-2 text-xs"
      data-testid="latex-build-result"
    >
      <div className="font-medium">
        {title}：
        {result.ok
          ? `完成${path ? ` · ${path}` : ''}`
          : `${result.code ?? 'failed'} · ${result.message ?? ''}`}
      </div>
      {result.ok && 'pdf_path' in result && result.pdf_path ? (
        <div className="text-muted mt-1">PDF：{result.pdf_path}</div>
      ) : null}
      {result.log_tail ? (
        <details className="mt-1">
          <summary className="cursor-pointer text-muted">日志</summary>
          <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap">{result.log_tail}</pre>
        </details>
      ) : null}
    </div>
  );
}

export interface LatexBuildPanelProps {
  workspacePath?: string | null;
}

export function LatexBuildPanel({ workspacePath: wsOverride }: LatexBuildPanelProps) {
  const activeWorkspace = useCurrentWorkspace() ?? null;
  const workspacePath = wsOverride ?? activeWorkspace;
  const canUse = Boolean(workspacePath && workspacePath.trim());

  const [capabilities, setCapabilities] = useState<LatexCapabilities | null>(null);
  const [filePath, setFilePath] = useState('');
  const [outputName, setOutputName] = useState('');
  const [engine, setEngine] = useState('');
  const [originalPath, setOriginalPath] = useState('');
  const [revisedPath, setRevisedPath] = useState('');
  const [diffName, setDiffName] = useState('');
  const [compilePdf, setCompilePdf] = useState(false);
  const [compileResult, setCompileResult] = useState<LatexCompileResult | null>(null);
  const [diffResult, setDiffResult] = useState<LatexDiffResult | null>(null);
  const [busy, setBusy] = useState<'compile' | 'diff' | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!canUse) return;
    let cancelled = false;
    getLatexCapabilities()
      .then((value) => {
        if (!cancelled) setCapabilities(value);
      })
      .catch(() => {
        if (!cancelled) setCapabilities(null);
      });
    return () => {
      cancelled = true;
    };
  }, [canUse]);

  const handleCompile = async () => {
    if (!canUse || !filePath.trim()) {
      setError('请先绑定工作区并填写 .tex 路径');
      return;
    }
    setBusy('compile');
    setError(null);
    try {
      setCompileResult(
        await compileLatex(
          workspacePath!,
          joinWorkspacePath(workspacePath!, filePath),
          outputName || undefined,
          engine || undefined,
        ),
      );
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const handleDiff = async () => {
    if (!canUse || !originalPath.trim() || !revisedPath.trim()) {
      setError('请先绑定工作区并填写原始/修订 .tex 路径');
      return;
    }
    setBusy('diff');
    setError(null);
    try {
      setDiffResult(
        await latexdiff(
          workspacePath!,
          joinWorkspacePath(workspacePath!, originalPath),
          joinWorkspacePath(workspacePath!, revisedPath),
          diffName,
          compilePdf,
          engine || undefined,
        ),
      );
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const engineNames = capabilities?.engines.map((item) => item.name) ?? [];

  return (
    <section
      className="flex flex-col gap-3 rounded border border-border p-4"
      data-testid="latex-build-panel"
    >
      <header>
        <h2 className="text-base font-semibold">LaTeX 编译与红字版</h2>
        <p className="text-xs text-muted">
          使用本机 TeX 引擎编译 PDF / 用 latexdiff 生成修改对比。不捆绑引擎；编译前会先做源码审校。
        </p>
        <p className="text-xs text-muted mt-1">
          引擎：{engineNames.length > 0 ? engineNames.join(', ') : '未检测到'} · latexdiff：
          {capabilities?.latexdiff ? '可用' : '未检测到'}
        </p>
      </header>

      <div className="flex flex-col gap-2 rounded border border-border p-3">
        <div className="text-sm font-medium">编译 PDF</div>
        <input
          className="rounded border border-border bg-bg px-2 py-1 text-sm"
          placeholder="paper/main.tex"
          value={filePath}
          onChange={(event) => setFilePath(event.target.value)}
          data-testid="latex-compile-path"
        />
        <div className="flex gap-2">
          <input
            className="flex-1 rounded border border-border bg-bg px-2 py-1 text-sm"
            placeholder="输出文件名（默认 <stem>.pdf）"
            value={outputName}
            onChange={(event) => setOutputName(event.target.value)}
            data-testid="latex-compile-output"
          />
          <select
            className="rounded border border-border bg-bg px-2 py-1 text-sm"
            value={engine}
            onChange={(event) => setEngine(event.target.value)}
            data-testid="latex-compile-engine"
          >
            <option value="">自动</option>
            {engineNames.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="rounded bg-accent px-3 py-1 text-sm text-white hover:opacity-90 disabled:opacity-50"
            onClick={handleCompile}
            disabled={busy !== null}
            data-testid="latex-compile-run"
          >
            {busy === 'compile' ? '编译中…' : '编译 PDF'}
          </button>
        </div>
        {compileResult ? <ResultBox title="编译" result={compileResult} /> : null}
      </div>

      <div className="flex flex-col gap-2 rounded border border-border p-3">
        <div className="text-sm font-medium">红字版（latexdiff）</div>
        <div className="flex gap-2">
          <input
            className="flex-1 rounded border border-border bg-bg px-2 py-1 text-sm"
            placeholder="原始版本 v1.tex"
            value={originalPath}
            onChange={(event) => setOriginalPath(event.target.value)}
            data-testid="latex-diff-original"
          />
          <input
            className="flex-1 rounded border border-border bg-bg px-2 py-1 text-sm"
            placeholder="修订版本 v2.tex"
            value={revisedPath}
            onChange={(event) => setRevisedPath(event.target.value)}
            data-testid="latex-diff-revised"
          />
        </div>
        <div className="flex gap-2 items-center">
          <input
            className="flex-1 rounded border border-border bg-bg px-2 py-1 text-sm"
            placeholder="输出 diff.tex（默认 <stem>-diff.tex）"
            value={diffName}
            onChange={(event) => setDiffName(event.target.value)}
            data-testid="latex-diff-output"
          />
          <label className="flex items-center gap-1 text-xs">
            <input
              type="checkbox"
              checked={compilePdf}
              onChange={(event) => setCompilePdf(event.target.checked)}
              data-testid="latex-diff-compile"
            />
            同时编译 PDF
          </label>
          <button
            type="button"
            className="rounded bg-accent px-3 py-1 text-sm text-white hover:opacity-90 disabled:opacity-50"
            onClick={handleDiff}
            disabled={busy !== null}
            data-testid="latex-diff-run"
          >
            {busy === 'diff' ? '生成中…' : '生成红字版'}
          </button>
        </div>
        {diffResult ? <ResultBox title="红字版" result={diffResult} /> : null}
      </div>

      {error ? <div className="text-sm text-error">{error}</div> : null}
    </section>
  );
}
