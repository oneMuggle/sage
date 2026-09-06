// src/widgets/settings/__tests__/HooksCard.test.tsx
// U9 hooks 配置 UI 测试 — invoke 全 mock。
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { HooksCard } from '../HooksCard';

const mockGet = vi.fn<() => Promise<{ value: string | null }>>();
const mockSet = vi.fn<(args: Record<string, unknown>) => Promise<void>>();

vi.mock('../../../shared/api/desktopInvoke', () => ({
  invoke: (cmd: string, args?: Record<string, unknown>) => {
    if (cmd === 'get_preference') return mockGet();
    if (cmd === 'set_preference') return mockSet(args ?? {});
    return Promise.resolve();
  },
}));

describe('HooksCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGet.mockResolvedValue({ value: null });
    mockSet.mockResolvedValue(undefined);
  });

  it('renders empty state then allows adding a hook', async () => {
    render(<HooksCard />);
    await waitFor(() => {
      expect(screen.getByTestId('hooks-add')).toBeInTheDocument();
    });
    expect(screen.getByText(/暂无自定义钩子/)).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('hooks-add'));
    await waitFor(() => {
      expect(mockSet).toHaveBeenCalled();
    });
    const saved = JSON.parse(
      (mockSet.mock.calls[0][0] as { value: string }).value,
    ) as Array<{ event: string; command: string }>;
    expect(saved).toHaveLength(1);
    expect(saved[0].event).toBe('pre_tool_use');
  });

  it('loads existing hooks from preferences', async () => {
    mockGet.mockResolvedValue({
      value: JSON.stringify([
        { event: 'stop', matcher: '*', command: 'echo done', timeout_seconds: 5 },
      ]),
    });
    render(<HooksCard />);
    await waitFor(() => {
      expect(screen.getByDisplayValue('echo done')).toBeInTheDocument();
    });
    expect(screen.getByText(/回复结束时/)).toBeInTheDocument();
  });

  it('edits command and saves', async () => {
    mockGet.mockResolvedValue({
      value: JSON.stringify([
        { event: 'pre_tool_use', matcher: '*', command: 'old', timeout_seconds: 10 },
      ]),
    });
    render(<HooksCard />);
    const commandInput = await screen.findByLabelText('命令');
    fireEvent.change(commandInput, { target: { value: 'new-cmd' } });
    await waitFor(() => {
      expect(mockSet).toHaveBeenCalled();
    });
    const saved = JSON.parse(
      (mockSet.mock.calls[0][0] as { value: string }).value,
    ) as Array<{ command: string }>;
    expect(saved[0].command).toBe('new-cmd');
    expect(mockSet.mock.calls[0][0].valueType).toBe('json');
  });

  it('deletes a hook', async () => {
    mockGet.mockResolvedValue({
      value: JSON.stringify([
        { event: 'stop', matcher: '*', command: 'a', timeout_seconds: 5 },
        { event: 'stop', matcher: '*', command: 'b', timeout_seconds: 5 },
      ]),
    });
    render(<HooksCard />);
    await waitFor(() => {
      expect(screen.getByDisplayValue('b')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByLabelText('删除钩子 1'));
    await waitFor(() => {
      expect(mockSet).toHaveBeenCalled();
    });
    const saved = JSON.parse(
      (mockSet.mock.calls[0][0] as { value: string }).value,
    ) as Array<{ command: string }>;
    expect(saved).toHaveLength(1);
    expect(saved[0].command).toBe('b');
  });

  it('tolerates invalid stored JSON', async () => {
    mockGet.mockResolvedValue({ value: 'not-json{{' });
    render(<HooksCard />);
    await waitFor(() => {
      expect(screen.getByText(/暂无自定义钩子/)).toBeInTheDocument();
    });
  });
});
