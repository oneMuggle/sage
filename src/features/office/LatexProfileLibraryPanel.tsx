import { useCallback, useEffect, useState } from 'react';

import {
  deleteLatexProfile,
  extractLatexProfile,
  listLatexProfiles,
  saveLatexProfile,
  type LatexProfileExtractResult,
  type LatexProfileRecord,
} from '../../shared/api/latexApi';
import { useCurrentWorkspace } from '../../shared/lib/workspaceContext';

import { LatexPathPicker } from './LatexPathPicker';
import { joinWorkspacePath } from './latexPath';

function defaultName(sourcePath: string): string {
  const name = sourcePath.split(/[\\/]/).pop() || 'profile';
  return name.replace(/\.(pdf|docx|txt|md|markdown)$/i, '') || 'profile';
}

export interface LatexProfileLibraryPanelProps {
  workspacePath?: string | null;
}

export function LatexProfileLibraryPanel({
  workspacePath: wsOverride,
}: LatexProfileLibraryPanelProps) {
  const activeWorkspace = useCurrentWorkspace() ?? null;
  const workspacePath = wsOverride ?? activeWorkspace;
  const canUse = Boolean(workspacePath && workspacePath.trim());

  const [profiles, setProfiles] = useState<LatexProfileRecord[]>([]);
  const [warnings, setWarnings] = useState<Array<{ code: string; message: string }>>([]);
  const [sourcePath, setSourcePath] = useState('');
  const [candidate, setCandidate] = useState<LatexProfileExtractResult | null>(null);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState<'list' | 'extract' | 'save' | 'delete' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!canUse) return;
    try {
      const value = await listLatexProfiles(workspacePath!);
      setProfiles(value.profiles);
      setWarnings(value.warnings);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [canUse, workspacePath]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleExtract = async () => {
    if (!canUse || !sourcePath.trim()) {
      setError('请先绑定工作区并填写指南文件路径');
      return;
    }
    setBusy('extract');
    setError(null);
    setSavedMessage(null);
    try {
      const result = await extractLatexProfile(
        workspacePath!,
        joinWorkspacePath(workspacePath!, sourcePath),
      );
      setCandidate(result);
      setName((current) => current || defaultName(sourcePath));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const handleSave = async () => {
    if (!canUse || !candidate || !name.trim()) {
      setError('请先提取并填写档案名称');
      return;
    }
    setBusy('save');
    setError(null);
    try {
      const saved = await saveLatexProfile(
        workspacePath!,
        name.trim(),
        candidate.profile,
        candidate.source_path,
        candidate.evidence,
      );
      setSavedMessage(`已保存：${saved.name}`);
      await refresh();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const handleDelete = async (profileName: string) => {
    if (!canUse) return;
    setBusy('delete');
    setError(null);
    try {
      await deleteLatexProfile(workspacePath!, profileName);
      await refresh();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <section
      className="flex flex-col gap-3 rounded border border-border p-4"
      data-testid="latex-profile-library-panel"
    >
      <header>
        <h2 className="text-base font-semibold">期刊规范档案</h2>
        <p className="text-xs text-muted">
          从作者指南（PDF/DOCX/TXT/MD）抽取候选合规档案，人工核对后保存到工作区
          .sage/latex-profiles，供投稿合规检查复用。
        </p>
      </header>

      <div className="flex gap-2">
        <LatexPathPicker
          value={sourcePath}
          onChange={setSourcePath}
          title="选择作者指南"
          extensions={['pdf', 'docx', 'txt', 'md', 'markdown']}
          placeholder="guidelines/ieee-author-guide.pdf"
          testId="latex-profile-source"
          className="flex-1"
        />
        <button
          type="button"
          className="rounded border border-border px-3 py-1 text-sm hover:bg-bg-hover disabled:opacity-50"
          onClick={handleExtract}
          disabled={busy !== null}
          data-testid="latex-profile-extract"
        >
          {busy === 'extract' ? '提取中…' : '从指南提取'}
        </button>
      </div>

      {candidate ? (
        <div
          className="flex flex-col gap-2 rounded border border-border bg-bg-subtle p-2 text-xs"
          data-testid="latex-profile-candidate"
        >
          <div className="font-medium">
            候选档案 · {candidate.profile.required_sections.length} 个章节 · 页数{' '}
            {candidate.profile.required_min_pages ?? '-'}–
            {candidate.profile.required_max_pages ?? '-'} · DPI {candidate.profile.min_image_dpi}
          </div>
          {candidate.warnings.length > 0 ? (
            <ul className="list-disc pl-4 text-warning">
              {candidate.warnings.map((warning) => (
                <li key={warning.code}>{warning.message}</li>
              ))}
            </ul>
          ) : null}
          {candidate.evidence.length > 0 ? (
            <details>
              <summary className="cursor-pointer text-muted">
                证据（{candidate.evidence.length}）
              </summary>
              <ul className="mt-1 flex flex-col gap-1">
                {candidate.evidence.map((item, index) => (
                  <li key={`${item.field}:${index}`} className="rounded border border-border p-1">
                    <span className="font-mono">{item.field}</span> = {String(item.value)}
                    <div className="text-muted">
                      {item.source}
                      {item.page ? ` · 第 ${item.page} 页` : ''}
                      {item.line ? ` · line ${item.line}` : ''}
                    </div>
                    <div className="text-muted">{item.snippet}</div>
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
          <div className="flex gap-2">
            <input
              className="flex-1 rounded border border-border bg-bg px-2 py-1 text-sm"
              placeholder="档案名称，如 ieee-2026"
              value={name}
              onChange={(event) => setName(event.target.value)}
              data-testid="latex-profile-name"
            />
            <button
              type="button"
              className="rounded bg-accent px-3 py-1 text-sm text-white hover:opacity-90 disabled:opacity-50"
              onClick={handleSave}
              disabled={busy !== null || !name.trim()}
              data-testid="latex-profile-save"
            >
              {busy === 'save' ? '保存中…' : '保存档案'}
            </button>
          </div>
        </div>
      ) : null}

      {savedMessage ? (
        <div className="text-sm text-success" data-testid="latex-profile-saved">
          {savedMessage}
        </div>
      ) : null}

      <div className="flex flex-col gap-1">
        <div className="text-xs text-muted">已保存档案：{profiles.length}</div>
        {warnings.map((warning) => (
          <div key={warning.code} className="text-xs text-warning">
            {warning.message}
          </div>
        ))}
        {profiles.map((profile) => (
          <div
            key={profile.name}
            className="flex items-center gap-2 rounded border border-border px-2 py-1 text-sm"
          >
            <span className="font-medium">{profile.name}</span>
            <span className="text-xs text-muted">{profile.source || 'manual'}</span>
            <span className="text-xs text-muted">{profile.updated_at}</span>
            <button
              type="button"
              className="ml-auto rounded border border-border px-2 py-1 text-xs hover:bg-bg-hover disabled:opacity-50"
              onClick={() => handleDelete(profile.name)}
              disabled={busy !== null}
              data-testid={`latex-profile-delete-${profile.name}`}
            >
              删除
            </button>
          </div>
        ))}
        <button
          type="button"
          className="w-fit rounded border border-border px-2 py-1 text-xs hover:bg-bg-hover"
          onClick={() => void refresh()}
          disabled={busy !== null}
          data-testid="latex-profile-refresh"
        >
          刷新
        </button>
      </div>

      {error ? <div className="text-sm text-error">{error}</div> : null}
    </section>
  );
}
