// @vitest-environment jsdom
import { act, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { Memory } from '../../../pages/Memory';
import { toast } from 'sonner';

vi.mock('sonner', () => ({
  toast: { success: vi.fn() },
}));

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  search: vi.fn(),
  getProfile: vi.fn(),
  getSummary: vi.fn(),
  delete: vi.fn(),
  invoke: vi.fn(),
  subscribe: vi.fn(),
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
  vi.clearAllMocks();
  mocks.list.mockResolvedValue([]);
  mocks.search.mockResolvedValue([]);
  mocks.getProfile.mockResolvedValue({ preferences: [], decisions: [], facts: [] });
  mocks.getSummary.mockResolvedValue({ summaries: [] });
  mocks.invoke.mockResolvedValue([]);
  // Default: subscribe works and returns an unsubscribe function.
  mocks.subscribe.mockImplementation(() => () => {});

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
        subscribe: (...args: unknown[]) => mocks.subscribe(...args),
      },
    },
  });
});

function renderPage() {
  return render(<Memory />, { wrapper: MemoryRouter });
}

describe('MemoryPage SSE integration', () => {
  it('subscribes to memory events on mount', () => {
    renderPage();
    expect(mocks.subscribe).toHaveBeenCalled();
  });

  it('prepends a new memory and shows a toast when an event arrives', async () => {
    const captured: Array<(evt: unknown) => void> = [];
    mocks.subscribe.mockImplementation((cb: (evt: unknown) => void) => {
      captured.push(cb);
      return () => {};
    });
    mocks.list.mockResolvedValue([BASE_ROW]);

    renderPage();
    await screen.findByText('记忆内容');

    // Simulate the Electron relay delivering a backend SSE payload.
    act(() => {
      captured[captured.length - 1](
        JSON.stringify({
          memory_id: 'new-1',
          content: '新记忆内容',
          memory_type: 'episodic',
          memory_category: 'user_pref',
          session_id: 's1',
          turn_id: 'turn-9',
          timestamp: '2026-08-05T00:00:00+00:00',
        }),
      );
    });

    expect(toast.success).toHaveBeenCalledWith('🧠 已记住: 新记忆内容');
    expect(await screen.findByText('新记忆内容')).toBeInTheDocument();
  });

  it('falls back to polling when subscribe throws (SSE unavailable)', () => {
    vi.useFakeTimers();
    mocks.subscribe.mockImplementation(() => {
      throw new Error('SSE unavailable');
    });
    mocks.list.mockResolvedValue([]);

    renderPage();
    act(() => {
      vi.advanceTimersByTime(30_000);
    });

    // Polling fallback reloads the list every 30s.
    expect(mocks.list).toHaveBeenCalled();
    vi.useRealTimers();
  });
});
