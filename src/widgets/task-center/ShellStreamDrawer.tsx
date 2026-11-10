// src/widgets/task-center/ShellStreamDrawer.tsx
//
// 2026-11-07 Phase 5: 后台 shell 输出抽屉。
// 由 DeliveryDrawerHost 挂载（shellStream 非空时渲染），内部复用
// ShellStreamPanel 的实时输出；running 状态提供「终止」按钮
// （invoke shell_kill → 后端 DELETE /api/v1/shells/{id}）。

import { X } from 'lucide-react';
import { useState } from 'react';

import { useTaskCenterStore } from '../../features/task-center/taskCenterStore';
import { invoke } from '../../shared/api/desktopInvoke';
import { useI18n } from '../../shared/lib/i18n';
import { ShellStreamPanel } from '../chat/progress/ShellStreamPanel';

interface ShellStreamDrawerProps {
  shellId: string;
}

export function ShellStreamDrawer({ shellId }: ShellStreamDrawerProps) {
  const { t } = useI18n();
  const closeShellStream = useTaskCenterStore((s) => s.closeShellStream);
  const entry = useTaskCenterStore((s) => s.tasks[`shell:${shellId}`]);
  const [terminating, setTerminating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const running = entry?.status === 'running';

  const handleTerminate = async (): Promise<void> => {
    if (terminating) return;
    setTerminating(true);
    setError(null);
    try {
      await invoke('shell_kill', { id: shellId });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setTerminating(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end" data-testid="shell-stream-drawer">
      <button
        type="button"
        aria-label={t('taskCenter.shellClose')}
        className="absolute inset-0 bg-overlay"
        onClick={closeShellStream}
      />
      <section className="relative flex h-full w-[520px] max-w-[90vw] flex-col border-l border-border bg-surface shadow-xl">
        <header className="flex items-center gap-2 border-b border-border px-3 py-2">
          <span className="flex-1 truncate text-xs font-medium" title={entry?.title ?? shellId}>
            {entry?.title ?? shellId}
          </span>
          <button
            type="button"
            onClick={closeShellStream}
            data-testid="shell-drawer-close"
            className="rounded p-1 hover:bg-bg-hover"
            aria-label={t('taskCenter.shellClose')}
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        </header>
        <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
          <ShellStreamPanel shellId={shellId} onClose={closeShellStream} />
          {error && <div className="text-xs text-error">{error}</div>}
        </div>
        {running && (
          <footer className="border-t border-border px-3 py-2">
            <button
              type="button"
              disabled={terminating}
              onClick={() => void handleTerminate()}
              data-testid="shell-drawer-terminate"
              className="rounded bg-error/10 px-2 py-1 text-xs text-error disabled:opacity-50"
            >
              {terminating ? t('taskCenter.shellTerminating') : t('taskCenter.shellTerminate')}
            </button>
          </footer>
        )}
      </section>
    </div>
  );
}
