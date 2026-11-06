// src/widgets/chat/progress/ShellStreamPanel.tsx
//
// 后台 shell 实时输出（2026-11-06 Phase 3）。
// 通过 desktopEvent.listen('shell-stream-{id}') 消费 Electron relay 转发的
// NDJSON；退出后保留最终输出并展示退出码。

import { useEffect, useRef, useState } from 'react';

import { listenShellStream, type ShellStreamEvent } from '../../../shared/api/shellApi';

/** 本地输出缓冲上限（字符），防止长跑任务无限占内存。 */
export const SHELL_STREAM_MAX_CHARS = 200_000;

interface ShellStreamPanelProps {
  shellId: string;
  onClose: () => void;
}

export function ShellStreamPanel({ shellId, onClose }: ShellStreamPanelProps) {
  const [output, setOutput] = useState('');
  const [exitCode, setExitCode] = useState<number | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const outputRef = useRef('');

  useEffect(() => {
    let disposed = false;
    let unlisten: (() => void) | null = null;
    outputRef.current = '';
    setOutput('');
    setExitCode(undefined);
    setError(null);

    listenShellStream(shellId, (event: ShellStreamEvent) => {
      if (disposed) return;
      if (event.type === 'output') {
        const chunk = event.stream === 'stderr' ? `[stderr] ${event.data}` : event.data;
        const next = (outputRef.current + chunk).slice(-SHELL_STREAM_MAX_CHARS);
        outputRef.current = next;
        setOutput(next);
      } else if (event.type === 'exit') {
        setExitCode(event.exit_code);
      }
    })
      .then((fn) => {
        if (disposed) fn();
        else unlisten = fn;
      })
      .catch((e: unknown) => {
        if (!disposed) setError(e instanceof Error ? e.message : String(e));
      });

    return () => {
      disposed = true;
      unlisten?.();
    };
  }, [shellId]);

  const statusText =
    exitCode === undefined
      ? '实时输出中…'
      : exitCode === null
        ? '已结束（退出码未知）'
        : `已结束 · exit=${exitCode}`;

  return (
    <section
      data-testid="shell-stream-panel"
      className="rounded border border-border p-2 space-y-2"
    >
      <header className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-text truncate" title={shellId}>
          {statusText}
        </span>
        <button
          type="button"
          className="text-xs text-text-secondary hover:text-text"
          onClick={onClose}
          data-testid="shell-stream-close"
        >
          关闭
        </button>
      </header>
      {error && <div className="text-xs text-error">{error}</div>}
      <pre
        data-testid="shell-stream-output"
        className="max-h-64 overflow-y-auto whitespace-pre-wrap break-all text-ui-2xs bg-bg-secondary rounded p-2"
      >
        {output || '等待输出…'}
      </pre>
    </section>
  );
}
