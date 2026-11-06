// src/widgets/chat/progress/BackgroundShellsSection.tsx
//
// 后台任务列表（2026-11-06 Phase 3）：展示注册表中的后台 shell，
// 点击行展开 ShellStreamPanel 实时查看输出。3s 轮询列表（轻量，仅
// 面板打开时存在）。

import { useEffect, useState } from 'react';

import { listShells, type ShellInfo } from '../../../shared/api/shellApi';
import { ShellStreamPanel } from './ShellStreamPanel';

export const SHELL_LIST_POLL_MS = 3_000;

export function BackgroundShellsSection() {
  const [shells, setShells] = useState<ShellInfo[]>([]);
  const [openShellId, setOpenShellId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = (): void => {
      listShells()
        .then((items) => {
          if (!cancelled) setShells(items);
        })
        .catch(() => {
          /* 静默：后台任务面板是增强信息 */
        });
    };
    load();
    const timer = window.setInterval(load, SHELL_LIST_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  if (shells.length === 0) return null;

  return (
    <section data-testid="background-shells-section" className="space-y-2">
      <h4 className="text-xs font-medium text-text-secondary">后台任务</h4>
      <ul className="space-y-1">
        {shells.map((shell) => (
          <li key={shell.shell_id}>
            <button
              type="button"
              className="w-full text-left rounded border border-border px-2 py-1 hover:bg-bg-secondary"
              onClick={() =>
                setOpenShellId((prev) => (prev === shell.shell_id ? null : shell.shell_id))
              }
              data-testid={`background-shell-${shell.shell_id}`}
            >
              <span className="block text-ui-2xs text-text truncate" title={shell.command}>
                {shell.command}
              </span>
              <span className="block text-ui-2xs text-text-tertiary">
                {shell.status === 'running' ? '运行中' : '已结束'} · {shell.age_seconds}s
              </span>
            </button>
          </li>
        ))}
      </ul>
      {openShellId && (
        <ShellStreamPanel shellId={openShellId} onClose={() => setOpenShellId(null)} />
      )}
    </section>
  );
}
