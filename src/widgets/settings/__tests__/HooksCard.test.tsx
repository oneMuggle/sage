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

const mockBackendRequest = vi.fn();
vi.mock('../../../shared/api/backendRequest', () => ({
  backendRequest: (req: { path: string }) => mockBackendRequest(req),
}));

const SAMPLE_BUILTINS = {
  builtins: [
    {
      id: 'security_guard',
      name: '安全守卫',
      description: '拦截危险 Shell 命令',
      icon: 'shield',
      event: 'pre_tool_use',
      matcher: 'bash',
      handler: 'backend.hooks.builtin_guards.security_guard',
      default_config: { blocklist: ['rm -rf /'] },
    },
    {
      id: 'audit_log',
      name: '操作审计日志',
      description: '记录所有工具调用',
      icon: 'file-text',
      event: 'post_tool_use',
      matcher: '*',
      handler: 'backend.hooks.builtin_audit.audit_logger',
      default_config: {},
    },
  ],
};

describe('HooksCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGet.mockResolvedValue({ value: null });
    mockSet.mockResolvedValue(undefined);
    mockBackendRequest.mockResolvedValue(SAMPLE_BUILTINS);
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

  // Phase 1: 内置钩子推荐区域
  it('renders builtin hooks from backend and shows toggle buttons', async () => {
    render(<HooksCard />);
    await waitFor(() => {
      expect(screen.getByText(/安全守卫/)).toBeInTheDocument();
    });
    expect(screen.getByText(/操作审计日志/)).toBeInTheDocument();
    expect(screen.getByTestId('builtin-toggle-security_guard').textContent).toBe('启用');
    expect(screen.getByTestId('builtin-toggle-audit_log').textContent).toBe('启用');
  });

  it('enabling a builtin adds entry with builtin_id to preferences', async () => {
    render(<HooksCard />);
    await waitFor(() => {
      expect(screen.getByTestId('builtin-toggle-security_guard')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId('builtin-toggle-security_guard'));
    await waitFor(() => {
      expect(mockSet).toHaveBeenCalled();
    });
    const saved = JSON.parse(
      (mockSet.mock.calls[0][0] as { value: string }).value,
    ) as Array<{ builtin_id?: string; hook_type?: string }>;
    expect(saved).toHaveLength(1);
    expect(saved[0].builtin_id).toBe('security_guard');
    expect(saved[0].hook_type).toBe('python');
  });

  it('already enabled builtin shows "已启用" and toggling removes it', async () => {
    mockGet.mockResolvedValue({
      value: JSON.stringify([
        {
          event: 'pre_tool_use',
          matcher: 'bash',
          command: '',
          hook_type: 'python',
          handler: 'backend.hooks.builtin_guards.security_guard',
          builtin_id: 'security_guard',
          timeout_seconds: 10,
        },
      ]),
    });
    render(<HooksCard />);
    await waitFor(() => {
      expect(screen.getByTestId('builtin-toggle-security_guard').textContent).toBe('已启用');
    });
    fireEvent.click(screen.getByTestId('builtin-toggle-security_guard'));
    await waitFor(() => {
      expect(mockSet).toHaveBeenCalled();
    });
    const saved = JSON.parse(
      (mockSet.mock.calls[0][0] as { value: string }).value,
    ) as unknown[];
    expect(saved).toHaveLength(0);
  });

  it('builtin entries do not appear in the custom hook CRUD table', async () => {
    mockGet.mockResolvedValue({
      value: JSON.stringify([
        {
          event: 'pre_tool_use',
          matcher: 'bash',
          command: '',
          hook_type: 'python',
          handler: 'backend.hooks.builtin_guards.security_guard',
          builtin_id: 'security_guard',
          timeout_seconds: 10,
        },
        { event: 'stop', matcher: '*', command: 'custom', timeout_seconds: 5 },
      ]),
    });
    render(<HooksCard />);
    await waitFor(() => {
      expect(screen.getByDisplayValue('custom')).toBeInTheDocument();
    });
    expect(screen.getAllByTestId('hook-row')).toHaveLength(1);
    expect(screen.getByTestId('builtin-toggle-security_guard').textContent).toBe('已启用');
  });

  it('gracefully degrades when backend builtins endpoint fails', async () => {
    mockBackendRequest.mockRejectedValue(new Error('network error'));
    render(<HooksCard />);
    await waitFor(() => {
      expect(screen.getByText(/暂无自定义钩子/)).toBeInTheDocument();
    });
    expect(screen.queryByText(/推荐 Hook/)).not.toBeInTheDocument();
  });
});
