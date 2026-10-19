/**
 * WorkspaceBindModal — Task 5 (2026-07-26).
 *
 * Single entry point for binding / changing / revoking a session's workspace
 * directory. Uses the Electron native folder picker (no browser fallback),
 * so it must run inside the desktop shell.
 *
 * The modal is fully controlled: callers pass the current binding path,
 * the `bind` / `revoke` actions, and `isOpen` / `onClose` lifecycle. This
 * keeps state ownership in SessionWorkspaceProvider — the modal only knows
 * how to translate user clicks into IPC.
 *
 * Stable test IDs (`workspace-bind-button`, `workspace-revoke-button`,
 * `workspace-bind-error`) are the contract that the integration test in
 * `src/pages/__tests__/Office.workspace.test.tsx` exercises end-to-end.
 */

import { FolderOpen, X } from 'lucide-react';
import { useCallback, useState } from 'react';

import { Modal } from '../../shared/ui/Modal';

export interface WorkspaceBindModalProps {
  isOpen: boolean;
  onClose: () => void;
  /** Active binding path, or `null` when no workspace is bound yet. */
  currentPath: string | null;
  /** Bind the active session to the chosen workspace directory. */
  bind: (workspacePath: string) => Promise<void>;
  /** Revoke the active session's binding (no-op when `currentPath` is null). */
  revoke: () => Promise<void>;
}

function errorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  return String(err);
}

export function WorkspaceBindModal({
  isOpen,
  onClose,
  currentPath,
  bind,
  revoke,
}: WorkspaceBindModalProps) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copiedPath, setCopiedPath] = useState(false);
  const [copiedMd, setCopiedMd] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

  const handleBind = useCallback(async () => {
    setError(null);
    const api = window.electronAPI;
    if (!api) {
      setError('IPC 桥接不可用,请在 Electron 桌面端运行');
      return;
    }
    setBusy(true);
    try {
      const picked = await api.selectDirectory({ intent: 'open' });
      if (!picked) return; // user cancelled
      await bind(picked);
      onClose();
    } catch (err: unknown) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }, [bind, onClose]);

  const handleRevoke = useCallback(async () => {
    setError(null);
    setBusy(true);
    try {
      await revoke();
      onClose();
    } catch (err: unknown) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }, [revoke, onClose]);

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="工作区目录">
      <div className="space-y-3">
        {currentPath ? (
          <div className="space-y-1.5 text-sm text-muted">
            <div>
              <span className="font-medium text-text">当前工作区:</span>{' '}
              <code
                className="px-1.5 py-0.5 rounded bg-bg-subtle text-text"
                data-testid="workspace-bind-current"
              >
                {currentPath}
              </code>
            </div>
            <div
              className="flex flex-wrap items-center gap-1.5"
              data-testid="workspace-bind-export-actions"
            >
              <button
                type="button"
                data-testid="workspace-bind-copy-path-btn"
                onClick={async () => {
                  setCopiedPath(true);
                  /* v8 ignore start */
                  setTimeout(() => {
                    if (typeof window !== 'undefined') setCopiedPath(false);
                  }, 1500);
                  try {
                    await navigator.clipboard?.writeText(currentPath);
                  } catch {
                    // ignore
                  }
                  /* v8 ignore stop */
                }}
                className="px-2 py-0.5 rounded border border-border bg-bg-subtle text-xs text-text-secondary hover:text-text"
              >
                {copiedPath ? '已复制路径' : '复制路径'}
              </button>
              <button
                type="button"
                data-testid="workspace-bind-copy-md-btn"
                onClick={async () => {
                  setCopiedMd(true);
                  const md = `# 当前绑定工作区\n- **目录路径**：\`${currentPath}\`\n- **绑定状态**：已绑定`;
                  /* v8 ignore start */
                  setTimeout(() => {
                    if (typeof window !== 'undefined') setCopiedMd(false);
                  }, 1500);
                  try {
                    await navigator.clipboard?.writeText(md);
                  } catch {
                    // ignore
                  }
                  /* v8 ignore stop */
                }}
                className="px-2 py-0.5 rounded border border-border bg-bg-subtle text-xs text-text-secondary hover:text-text"
              >
                {copiedMd ? '已复制MD' : '复制绑定MD'}
              </button>
              <button
                type="button"
                data-testid="workspace-bind-copy-json-btn"
                onClick={async () => {
                  setCopiedJson(true);
                  /* v8 ignore start */
                  setTimeout(() => {
                    if (typeof window !== 'undefined') setCopiedJson(false);
                  }, 1500);
                  try {
                    await navigator.clipboard?.writeText(
                      JSON.stringify({ workspacePath: currentPath, bound: true }, null, 2),
                    );
                  } catch {
                    // ignore
                  }
                  /* v8 ignore stop */
                }}
                className="px-2 py-0.5 rounded border border-border bg-bg-subtle text-xs text-text-secondary hover:text-text"
              >
                {copiedJson ? '已复制JSON' : '复制绑定JSON'}
              </button>
            </div>
          </div>
        ) : (
          <div className="text-sm text-muted">
            尚未绑定工作区目录。请选择一个文件夹,Sage 会用它来管理 Office 文档。
          </div>
        )}

        {error && (
          <div
            data-testid="workspace-bind-error"
            className="px-3 py-2 rounded border border-error/30 bg-error/10 text-error text-sm"
          >
            {error}
          </div>
        )}

        <div className="flex items-center justify-end gap-2 pt-2">
          <button
            type="button"
            data-testid="workspace-revoke-button"
            onClick={handleRevoke}
            disabled={!currentPath || busy}
            className="px-3 py-1.5 rounded border border-border bg-bg-subtle text-text hover:bg-border/30 disabled:opacity-50 disabled:cursor-not-allowed text-sm"
          >
            <X className="inline w-4 h-4 mr-1" /> 解除绑定
          </button>
          <button
            type="button"
            data-testid="workspace-bind-button"
            onClick={handleBind}
            disabled={busy}
            className="px-3 py-1.5 rounded bg-primary text-text-inverse hover:bg-primary-hover disabled:opacity-50 disabled:cursor-not-allowed text-sm"
          >
            <FolderOpen className="inline w-4 h-4 mr-1" />
            {currentPath ? '更换目录' : '选择目录'}
          </button>
        </div>
      </div>
    </Modal>
  );
}