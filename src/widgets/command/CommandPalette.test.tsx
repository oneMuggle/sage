/**
 * P1-3.7 全局搜索合并：CommandPalette 在搜索词 >= 2 字符时切换到
 * 后端全局搜索结果（会话 / 记忆 / 知识库分组），< 2 字符时保持命令模式。
 *
 * backendRequest 被 mock，避免依赖 Electron IPC bridge。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../shared/lib/i18n';
import { useStore } from '../../shared/lib/store';

import { CommandPalette } from './CommandPalette';

const mockBackendRequest = vi.fn();
vi.mock('../../shared/api/backendRequest', () => ({
  backendRequest: (...args: unknown[]) => mockBackendRequest(...args),
}));

vi.mock('../../app/providers/useTheme', () => ({
  useTheme: () => ({ resolved: 'light', setMode: vi.fn() }),
}));

// jsdom 不实现 ResizeObserver / scrollIntoView，但 cmdk 内部使用它们。
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}
if (typeof Element.prototype.scrollIntoView === 'undefined') {
  Element.prototype.scrollIntoView = function scrollIntoView() {};
}

function renderPalette() {
  return render(
    <MemoryRouter>
      <I18nProvider>
        <CommandPalette open onOpenChange={() => {}} />
      </I18nProvider>
    </MemoryRouter>,
  );
}

describe('CommandPalette 全局搜索 (P1-3.7)', () => {
  beforeEach(() => {
    useStore.setState({ sessions: [], currentSessionId: null });
    mockBackendRequest.mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('搜索词 < 2 字符时不请求后端，显示命令模式', () => {
    renderPalette();
    expect(screen.getByText('导航')).toBeInTheDocument();
    expect(mockBackendRequest).not.toHaveBeenCalled();
  });

  it('搜索词 >= 2 字符时调用 /api/v1/search/global 并渲染三类结果', async () => {
    mockBackendRequest.mockResolvedValue({
      sessions: [{ id: 's1', title: '项目计划', updated_at: 1, message_count: 3 }],
      memories: [
        {
          id: 'm1',
          content: '记住用户偏好深色主题',
          memory_type: 'preference',
          importance: 1,
          tags: [],
        },
      ],
      knowledge: [{ path: 'a.md', title: '架构说明', snippet: '系统架构概述' }],
    });

    renderPalette();

    fireEvent.change(screen.getByPlaceholderText('输入命令或搜索...'), {
      target: { value: '项目' },
    });

    await waitFor(() => {
      expect(mockBackendRequest).toHaveBeenCalledWith({
        path: expect.stringContaining('/api/v1/search/global?'),
      });
    });

    await waitFor(() => {
      expect(screen.getByText('项目计划')).toBeInTheDocument();
      expect(screen.getByText('记住用户偏好深色主题')).toBeInTheDocument();
      expect(screen.getByText('架构说明')).toBeInTheDocument();
    });
  });

  it('后端不可用时静默降级（不抛错、不渲染结果）', async () => {
    mockBackendRequest.mockRejectedValue(new Error('BACKEND_NOT_AVAILABLE'));

    renderPalette();

    fireEvent.change(screen.getByPlaceholderText('输入命令或搜索...'), {
      target: { value: '项目' },
    });

    await waitFor(() => {
      expect(mockBackendRequest).toHaveBeenCalled();
    });
    expect(screen.queryByText('项目计划')).not.toBeInTheDocument();
  });
});
