import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { HookHistoryPanel } from '../HookHistoryPanel';

const mockBackendRequest = vi.fn();

vi.mock('../../../shared/api/backendRequest', () => ({
  backendRequest: (request: unknown) => mockBackendRequest(request),
}));

describe('HookHistoryPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockBackendRequest.mockResolvedValue({ records: [] });
  });

  it('shows empty state after loading', async () => {
    render(<HookHistoryPanel />);
    await waitFor(() => expect(screen.getByText('暂无执行记录')).toBeInTheDocument());
    expect(mockBackendRequest).toHaveBeenCalledWith({
      method: 'GET',
      path: '/api/v1/hooks/history?limit=50',
    });
  });

  it('renders records with decision, hook id, reason and duration', async () => {
    mockBackendRequest.mockResolvedValueOnce({
      records: [
        {
          id: '1',
          occurred_at: '2026-09-19T15:42:00Z',
          hook_id: 'security_guard',
          hook_type: 'python',
          event: 'pre_tool_use',
          tool_name: 'bash',
          decision: 'deny',
          duration_ms: 12.7,
          reason: '危险命令被拦截',
        },
      ],
    });
    render(<HookHistoryPanel />);
    await waitFor(() => expect(screen.getByText('拒绝')).toBeInTheDocument());
    expect(screen.getByText(/security_guard → bash/)).toBeInTheDocument();
    expect(screen.getByText(/危险命令被拦截/)).toBeInTheDocument();
    expect(screen.getByText('13ms')).toBeInTheDocument();
  });

  it('clears history', async () => {
    mockBackendRequest.mockResolvedValueOnce({
      records: [
        {
          id: '1',
          occurred_at: '2026-09-19T15:42:00Z',
          hook_id: 'audit_log',
          hook_type: 'python',
          event: 'post_tool_use',
          tool_name: 'bash',
          decision: 'allow',
          duration_ms: 1,
        },
      ],
    });
    mockBackendRequest.mockResolvedValueOnce({ ok: true, deleted: 1 });
    render(<HookHistoryPanel />);
    const clearButton = await screen.findByRole('button', { name: '清空' });
    fireEvent.click(clearButton);
    await waitFor(() => {
      expect(mockBackendRequest).toHaveBeenCalledWith({
        method: 'DELETE',
        path: '/api/v1/hooks/history',
      });
    });
    await waitFor(() => expect(screen.getByText('暂无执行记录')).toBeInTheDocument());
  });

  it('fails open when history endpoint errors', async () => {
    mockBackendRequest.mockRejectedValue(new Error('offline'));
    render(<HookHistoryPanel />);
    await waitFor(() => expect(screen.getByText('暂无执行记录')).toBeInTheDocument());
  });
});
