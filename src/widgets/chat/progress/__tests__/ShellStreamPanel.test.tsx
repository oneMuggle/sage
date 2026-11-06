// ShellStreamPanel 测试（2026-11-06 Phase 3）
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

type Handler = (event: unknown) => void;
let captured: Handler | null = null;
const unlistenMock = vi.fn();
const listenMock = vi.fn(async (_id: string, cb: Handler) => {
  captured = cb;
  return unlistenMock;
});

vi.mock('../../../../shared/api/shellApi', () => ({
  listenShellStream: (id: string, cb: Handler) => listenMock(id, cb),
}));

import { ShellStreamPanel } from '../ShellStreamPanel';

beforeEach(() => {
  vi.clearAllMocks();
  captured = null;
});

describe('ShellStreamPanel', () => {
  it('accumulates stdout/stderr and shows exit code', async () => {
    const onClose = vi.fn();
    render(<ShellStreamPanel shellId="sh-1" onClose={onClose} />);
    await waitFor(() => expect(listenMock).toHaveBeenCalledWith('sh-1', expect.any(Function)));

    expect(screen.getByText('实时输出中…')).toBeInTheDocument();

    act(() => captured?.({ type: 'output', stream: 'stdout', data: 'hello\n' }));
    act(() => captured?.({ type: 'output', stream: 'stderr', data: 'warn\n' }));

    const output = screen.getByTestId('shell-stream-output');
    expect(output.textContent).toContain('hello');
    expect(output.textContent).toContain('[stderr] warn');

    act(() => captured?.({ type: 'exit', exit_code: 0 }));
    expect(screen.getByText('已结束 · exit=0')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('shell-stream-close'));
    expect(onClose).toHaveBeenCalled();
  });

  it('shows unknown exit code when exit_code is null', async () => {
    render(<ShellStreamPanel shellId="sh-2" onClose={vi.fn()} />);
    await waitFor(() => expect(listenMock).toHaveBeenCalled());
    act(() => captured?.({ type: 'exit', exit_code: null }));
    expect(screen.getByText('已结束（退出码未知）')).toBeInTheDocument();
  });

  it('unsubscribes on unmount', async () => {
    const { unmount } = render(<ShellStreamPanel shellId="sh-3" onClose={vi.fn()} />);
    await waitFor(() => expect(listenMock).toHaveBeenCalled());
    unmount();
    expect(unlistenMock).toHaveBeenCalled();
  });
});
