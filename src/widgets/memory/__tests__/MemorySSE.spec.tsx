// @vitest-environment jsdom
import { act, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { toast } from 'sonner';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { Memory } from '../../../pages/Memory';

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
  // Default: subscribe succeeds (main relay OK) and returns an unsubscribe fn.
  mocks.subscribe.mockResolvedValue(() => {});

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
      return Promise.resolve(() => {});
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

  it('falls back to polling when subscribe resolves null (main relay unavailable)', async () => {
    // REAL failure mode: preload's invoke rejects (or main reports
    // { subscribed: false }) → subscribe resolves null, NOT a sync throw.
    vi.useFakeTimers();
    mocks.subscribe.mockResolvedValue(null);
    mocks.list.mockResolvedValue([]);

    renderPage();
    // Flush the subscribe promise resolution (Memory.tsx starts polling in .then).
    await act(async () => {});
    const callsAfterMount = mocks.list.mock.calls.length;
    expect(callsAfterMount).toBeGreaterThanOrEqual(1);

    // Advance past the 30s polling interval — the list must be reloaded.
    act(() => {
      vi.advanceTimersByTime(30_000);
    });
    await act(async () => {});

    expect(mocks.list.mock.calls.length).toBeGreaterThan(callsAfterMount);
    vi.useRealTimers();
  });

  it('falls back to polling when subscribe rejects', async () => {
    vi.useFakeTimers();
    mocks.subscribe.mockRejectedValue(new Error('main relay crashed'));
    mocks.list.mockResolvedValue([]);

    renderPage();
    await act(async () => {});
    const callsAfterMount = mocks.list.mock.calls.length;

    act(() => {
      vi.advanceTimersByTime(30_000);
    });
    await act(async () => {});

    expect(mocks.list.mock.calls.length).toBeGreaterThan(callsAfterMount);
    vi.useRealTimers();
  });
});
