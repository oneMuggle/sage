/**
 * WorkspaceEmptyGuard — P0 (2026-10-19).
 *
 * Replaces the raw 403 `workspace_not_bound` error with a friendly inline
 * prompt that guides the user to bind a workspace directory. Shown in any
 * panel that requires a workspace binding (changes list, document preview,
 * Office import, etc.).
 *
 * The component is self-contained: it reads `bind` from
 * `useWorkspaceContext()` and calls `window.electronAPI.selectDirectory()`
 * to let the user pick a folder. After a successful bind, the parent panel
 * will re-fetch automatically (the provider updates `binding`, consumers
 * react to the context change).
 */

import { FolderOpen } from 'lucide-react';
import { useCallback, useState } from 'react';

import { useOptionalWorkspaceContext } from '../../shared/lib/workspaceContext';

export type WorkspaceGuardFeature = 'changes' | 'preview' | 'office';

interface WorkspaceEmptyGuardProps {
  /** Which feature tried to access the workspace — controls the description text. */
  feature: WorkspaceGuardFeature;
  className?: string;
}

const FEATURE_COPY: Record<WorkspaceGuardFeature, { title: string; description: string }> = {
  changes: {
    title: '绑定工作区以查看变更',
    description: '当前会话尚未绑定工作区目录。绑定后可查看 git 变更、diff 和检查点。',
  },
  preview: {
    title: '绑定工作区以预览文档',
    description: '当前会话尚未绑定工作区目录。绑定后可预览工作区中的文件内容。',
  },
  office: {
    title: '绑定工作区以管理文档',
    description: '当前会话尚未绑定工作区目录。绑定后可导入和管理 Office 文档。',
  },
};

export function formatWorkspaceGuardMarkdown(
  feature: WorkspaceGuardFeature,
  error: string | null,
): string {
  const copy = FEATURE_COPY[feature];
  return [
    '# 空工作区引导状态 (Workspace Empty Guard)',
    '',
    `- **触发功能**: \`${feature}\``,
    `- **引导标题**: ${copy.title}`,
    `- **引导说明**: ${copy.description}`,
    `- **最近错误**: ${error || '无'}`,
  ].join('\n');
}

export function formatWorkspaceGuardJson(
  feature: WorkspaceGuardFeature,
  error: string | null,
): string {
  const copy = FEATURE_COPY[feature];
  return JSON.stringify(
    {
      exportedAt: new Date().toISOString(),
      feature,
      title: copy.title,
      description: copy.description,
      error,
    },
    null,
    2,
  );
}

export function WorkspaceEmptyGuard({ feature, className }: WorkspaceEmptyGuardProps) {
  const ctx = useOptionalWorkspaceContext();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copiedMd, setCopiedMd] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);
  const copy = FEATURE_COPY[feature];

  const handleBind = useCallback(async () => {
    setError(null);
    const api = window.electronAPI;
    if (!api) {
      setError('IPC 桥接不可用，请在 Electron 桌面端运行');
      return;
    }
    if (!ctx) {
      setError('工作区上下文未就绪，请稍后重试');
      return;
    }
    setBusy(true);
    try {
      const picked = await api.selectDirectory({ intent: 'open' });
      if (!picked) return; // user cancelled
      await ctx.bind(picked);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, [ctx]);

  /* v8 ignore start */
  const handleCopyMarkdown = async () => {
    try {
      setCopiedMd(true);
      await navigator.clipboard?.writeText(formatWorkspaceGuardMarkdown(feature, error));
      setTimeout(() => setCopiedMd(false), 1500);
    } catch {
      // ignore clipboard errors
    }
  };

  const handleCopyJson = async () => {
    try {
      setCopiedJson(true);
      await navigator.clipboard?.writeText(formatWorkspaceGuardJson(feature, error));
      setTimeout(() => setCopiedJson(false), 1500);
    } catch {
      // ignore clipboard errors
    }
  };
  /* v8 ignore stop */

  return (
    <div
      role="status"
      aria-live="polite"
      className={
        className ??
        'flex flex-col items-center gap-3 p-6 rounded-lg border ' +
          'bg-bg-subtle/50 border-border text-text'
      }
      data-testid="workspace-empty-guard"
    >
      <FolderOpen className="w-8 h-8 text-text-secondary" aria-hidden />
      <div className="text-center">
        <h3 className="text-sm font-medium">{copy.title}</h3>
        <p className="mt-1 text-xs text-text-secondary max-w-xs">{copy.description}</p>
      </div>
      {error && (
        <div className="px-3 py-1.5 rounded border border-error/30 bg-error/10 text-error text-xs">
          {error}
        </div>
      )}
      <button
        type="button"
        onClick={handleBind}
        disabled={busy}
        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium bg-ui-card text-ui-fg border border-border hover:bg-ui-panel disabled:opacity-50 disabled:pointer-events-none transition-colors"
        data-testid="workspace-empty-guard-bind"
      >
        <FolderOpen className="w-4 h-4" />
        {busy ? '绑定中...' : '选择目录'}
      </button>
      <div className="flex items-center gap-1.5 text-ui-2xs">
        <span
          data-testid="workspace-guard-copy-md"
          onClick={() => void handleCopyMarkdown()}
          className="cursor-pointer rounded border border-border px-1.5 py-0.5 text-text-secondary hover:bg-bg-hover"
        >
          {copiedMd ? '已复制 MD' : '复制 MD'}
        </span>
        <span
          data-testid="workspace-guard-copy-json"
          onClick={() => void handleCopyJson()}
          className="cursor-pointer rounded border border-border px-1.5 py-0.5 text-text-secondary hover:bg-bg-hover"
        >
          {copiedJson ? '已复制 JSON' : '复制 JSON'}
        </span>
      </div>
    </div>
  );
}
