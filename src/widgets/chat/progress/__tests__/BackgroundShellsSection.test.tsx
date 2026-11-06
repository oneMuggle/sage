// BackgroundShellsSection 测试（2026-11-06 Phase 3）
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const listMock = vi.fn();
vi.mock('../../../../shared/api/shellApi', () => ({
  listShells: () => listMock(),
}));

vi.mock('../ShellStreamPanel', () => ({
  ShellStreamPanel: ({ shellId }: { shellId: string }) => (
    <div data-testid="shell-stream-panel-stub">{shellId}</div>
  ),
}));

import { BackgroundShellsSection } from '../BackgroundShellsSection';

beforeEach(() => {
  vi.clearAllMocks();
  listMock.mockResolvedValue([]);
});

describe('BackgroundShellsSection', () => {
  it('renders nothing when no background shells', async () => {
    const { container } = render(<BackgroundShellsSection />);
    await waitFor(() => expect(listMock).toHaveBeenCalled());
    expect(container.querySelector('[data-testid="background-shells-section"]')).toBeNull();
  });

  it('lists shells and opens the stream panel on click', async () => {
    listMock.mockResolvedValue([
      {
        shell_id: 'sh-1',
        command: 'pytest -q',
        status: 'running',
        pid: 123,
        age_seconds: 42,
      },
      {
        shell_id: 'sh-2',
        command: 'npm run build',
        status: 'exited',
        pid: 456,
        age_seconds: 7,
      },
    ]);
    render(<BackgroundShellsSection />);

    await waitFor(() => expect(screen.getByTestId('background-shell-sh-1')).toBeInTheDocument());
    expect(screen.getByText('pytest -q')).toBeInTheDocument();
    expect(screen.getByText(/运行中 · 42s/)).toBeInTheDocument();
    expect(screen.getByText(/已结束 · 7s/)).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('background-shell-sh-1'));
    expect(screen.getByTestId('shell-stream-panel-stub').textContent).toBe('sh-1');

    // 再次点击同一行收起面板
    fireEvent.click(screen.getByTestId('background-shell-sh-1'));
    expect(screen.queryByTestId('shell-stream-panel-stub')).toBeNull();
  });
});
