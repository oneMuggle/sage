import { useState } from 'react';

import {
  extractLatexProject,
  type LatexProjectExtractResult,
} from '../../shared/api/latexApi';
import { useCurrentWorkspace } from '../../shared/lib/workspaceContext';

import { joinWorkspacePath } from './latexPath';

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MiB`;
}

export interface LatexProjectImportPanelProps {
  workspacePath?: string | null;
}

export function LatexProjectImportPanel({
  workspacePath: wsOverride,
}: LatexProjectImportPanelProps) {
  const activeWorkspace = useCurrentWorkspace() ?? null;
  const workspacePath = wsOverride ?? activeWorkspace;
  const canUse = Boolean(workspacePath && workspacePath.trim());

  const [zipPath, setZipPath] = useState('');
  const [outputDir, setOutputDir] = useState('');
  const [result, setResult] = useState<LatexProjectExtractResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleExtract = async () => {
    if (!canUse || !zipPath.trim()) {
      setError('请先绑定工作区并填写 .zip 路径');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setResult(
        await extractLatexProject(
          workspacePath!,
          joinWorkspacePath(workspacePath!, zipPath),
          outputDir.trim() || undefined,
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
      data-testid="latex-project-import-panel"
    >
      <header>
        <h2 className="text-base font-semibold">LaTeX 项目导入</h2>
        <p className="text-xs text-muted">
          安全解压 Overleaf / 期刊模板 zip 到工作区新目录，并识别主 .tex 文件。
          拒绝路径穿越、符号链接与 zip bomb；解压内容不会被执行或编译。
        </p>
      </header>

      <input
        className="rounded border border-border bg-bg px-2 py-1 text-sm"
        placeholder="下载/ieee-template.zip"
        value={zipPath}
        onChange={(event) => setZipPath(event.target.value)}
        data-testid="latex-project-zip-path"
      />
      <div className="flex gap-2">
        <input
          className="flex-1 rounded border border-border bg-bg px-2 py-1 text-sm"
          placeholder="输出目录名（默认 latex-<zip 名>）"
          value={outputDir}
          onChange={(event) => setOutputDir(event.target.value)}
          data-testid="latex-project-output-dir"
        />
        <button
          type="button"
          className="rounded bg-accent px-3 py-1 text-sm text-white hover:opacity-90 disabled:opacity-50"
          onClick={handleExtract}
          disabled={busy}
          data-testid="latex-project-extract"
        >
          {busy ? '解压中…' : '解压项目'}
        </button>
      </div>

      {result ? (
        <div
          className="rounded border border-border bg-bg-subtle p-2 text-xs"
          data-testid="latex-project-result"
        >
          <div className="font-medium">
            项目目录：{result.project_dir} · {result.files_count} 个文件 ·{' '}
            {formatBytes(result.bytes_written)}
          </div>
          <div className="text-muted mt-1">
            主文件：{result.main_file ?? '未识别（可手动填写主 .tex 路径）'}
          </div>
          {result.main_candidates.length > 1 ? (
            <div className="text-muted mt-1">
              候选：{result.main_candidates.join(', ')}
            </div>
          ) : null}
          {result.warnings.length > 0 ? (
            <ul className="mt-1 list-disc pl-4 text-muted">
              {result.warnings.map((warning) => (
                <li key={`${warning.code}:${warning.path ?? warning.message}`}>
                  {warning.message}
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
