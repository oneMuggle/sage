// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { Memory } from '../Memory';

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  search: vi.fn(),
  getProfile: vi.fn(),
  getSummary: vi.fn(),
  delete: vi.fn(),
  invoke: vi.fn(),
}));

const BASE_ROW = {
  id: 'm1',
  content: '记忆内容',
  importance: 6,
  memory_type: 'episodic',
  memory_category: 'user_pref',
  session_id: 's1',
  source_turn_id: 'turn-1',
  created_at: '2026-08-04T17:30:00Z',
};

beforeEach(() => {
  mocks.list.mockReset();
  mocks.search.mockReset();
  mocks.getProfile.mockReset();
  mocks.getSummary.mockReset();
  mocks.delete.mockReset();
  mocks.invoke.mockReset();

  mocks.list.mockResolvedValue([]);
  mocks.search.mockResolvedValue([]);
  mocks.getProfile.mockResolvedValue({ preferences: [], decisions: [], facts: [], total_count: 0 });
  mocks.getSummary.mockResolvedValue({ summaries: [], session_id: 's1' });
  mocks.invoke.mockResolvedValue([]);

  Object.defineProperty(window, 'electronAPI', {
    configurable: true,
    value: {
      invoke: (...args: unknown[]) => mocks.invoke(...args),
      memory: {
        list: (...args: unknown[]) => mocks.list(...args),
        search: (...args: unknown[]) => mocks.search(...args),
        getProfile: (...args: unknown[]) => mocks.getProfile(...args),
        getSummary: (...args: unknown[]) => mocks.getSummary(...args),
        delete: (...args: unknown[]) => mocks.delete(...args),
      },
    },
  });
});

function renderPage() {
  return render(<Memory />, { wrapper: MemoryRouter });
}

describe('Memory page', () => {
  it('renders the 3 tabs', () => {
    renderPage();
    expect(screen.getByText('所有记忆')).toBeInTheDocument();
    expect(screen.getByText('用户档案')).toBeInTheDocument();
    expect(screen.getByText('会话摘要')).toBeInTheDocument();
  });

  it('includes cross_session_pattern in the type filter dropdown', () => {
    renderPage();
    const select = screen.getByLabelText('按类型筛选');
    expect(select).toHaveTextContent('跨会话模式');
    expect(select).toHaveTextContent('用户偏好');
  });

  it('loads memories via memory.list on the all tab', async () => {
    mocks.list.mockResolvedValue([BASE_ROW]);
    renderPage();
    expect(await screen.findByText('记忆内容')).toBeInTheDocument();
    expect(mocks.list).toHaveBeenCalled();
  });

  it('loads profile data when profile tab selected', async () => {
    mocks.getProfile.mockResolvedValue({
      preferences: [{ ...BASE_ROW, id: 'p1', content: '偏好内容' }],
      decisions: [],
      facts: [],
      total_count: 1,
    });
    renderPage();
    fireEvent.click(screen.getByText('用户档案'));
    expect(await screen.findByText('偏好内容')).toBeInTheDocument();
    expect(mocks.getProfile).toHaveBeenCalled();
  });

  it('loads session summaries when summary tab selected', async () => {
    mocks.invoke.mockResolvedValue([{ id: 's1', title: '会话1' }]);
    mocks.getSummary.mockResolvedValue({
      summaries: [
        { ...BASE_ROW, id: 'su1', content: '会话总结内容', memory_category: 'task_summary' },
      ],
      session_id: 's1',
    });
    renderPage();
    fireEvent.click(screen.getByText('会话摘要'));
    expect(await screen.findByText('会话总结内容')).toBeInTheDocument();
    expect(mocks.getSummary).toHaveBeenCalledWith({ session_id: 's1' });
  });

  it('deletes a memory via memory.delete', async () => {
    mocks.list.mockResolvedValue([BASE_ROW]);
    mocks.delete.mockResolvedValue({ status: 'ok' });
    renderPage();
    await screen.findByText('记忆内容');
    fireEvent.click(screen.getByRole('button', { name: /删除/ }));
    await waitFor(() => expect(mocks.delete).toHaveBeenCalledWith({ memory_id: 'm1' }));
    await waitFor(() => expect(screen.queryByText('记忆内容')).not.toBeInTheDocument());
  });

  it('falls back to empty state when electronAPI is absent', () => {
    Object.defineProperty(window, 'electronAPI', { configurable: true, value: undefined });
    renderPage();
    expect(screen.getByText(/暂无记忆/)).toBeInTheDocument();
  });
});
