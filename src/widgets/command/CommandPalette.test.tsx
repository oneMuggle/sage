/**
 * P1-3.7 全局搜索合并：CommandPalette 在搜索词 >= 2 字符时切换到
 * 后端全局搜索结果（会话 / 记忆 / 知识库分组），< 2 字符时保持命令模式。
 *
 * 项目模块 P2：新增"项目"分组（打开项目）与 add-project 操作命令。
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

const projectListMock = vi.fn();
const projectOpenMock = vi.fn();
const projectRegisterMock = vi.fn();
vi.mock('../../shared/api/projectApi', () => ({
  projectApi: {
    list: (...args: unknown[]) => projectListMock(...args),
    open: (...args: unknown[]) => projectOpenMock(...args),
    register: (...args: unknown[]) => projectRegisterMock(...args),
    remove: vi.fn(),
    createSession: vi.fn(),
    listSessions: vi.fn(),
  },
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
    // P2: 面板打开即拉项目清单 —— 本组用例须给默认实现，否则 mock 返回
    // undefined 使组件 effect 的 .then 链抛错（与本组断言无关的崩溃）。
    projectListMock.mockReset();
    projectListMock.mockResolvedValue([]);
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

describe('CommandPalette 项目模块 (P2)', () => {
  const projects = [
    {
      id: 'p1',
      path: 'C:\\work\\demo',
      name: 'demo',
      createdAt: 1,
      lastOpenedAt: 10,
      sessionCount: 2,
      lastSessionId: 's1',
    },
  ];

  beforeEach(() => {
    useStore.setState({ sessions: [], currentSessionId: null });
    mockBackendRequest.mockReset();
    projectListMock.mockReset();
    projectOpenMock.mockReset();
    projectRegisterMock.mockReset();
    projectListMock.mockResolvedValue([]);
  });

  afterEach(() => {
    vi.clearAllMocks();
    delete (window as unknown as { electronAPI?: unknown }).electronAPI;
  });

  it('面板打开时渲染"项目"分组并列出项目名与路径', async () => {
    projectListMock.mockResolvedValue(projects);
    renderPalette();

    await waitFor(() => {
      expect(projectListMock).toHaveBeenCalled();
      expect(screen.getByText('demo')).toBeInTheDocument();
      expect(screen.getByText('C:\\work\\demo')).toBeInTheDocument();
    });
  });

  it('选择项目条目 → projects_open → 切换到返回的会话', async () => {
    projectListMock.mockResolvedValue(projects);
    projectOpenMock.mockResolvedValue({
      project: projects[0],
      session: {
        id: 's-opened',
        title: 'demo',
        created_at: 1,
        updated_at: 1,
        last_message_at: null,
        message_count: 0,
        is_pinned: false,
      },
      created: false,
    });
    renderPalette();

    await waitFor(() => screen.getByText('demo'));
    fireEvent.click(screen.getByText('demo'));

    await waitFor(() => {
      expect(projectOpenMock).toHaveBeenCalledWith('p1');
      expect(useStore.getState().currentSessionId).toBe('s-opened');
    });
  });

  it('项目清单加载失败静默降级为不显示分组', async () => {
    projectListMock.mockRejectedValue(new Error('backend offline'));
    renderPalette();

    await waitFor(() => {
      expect(projectListMock).toHaveBeenCalled();
    });
    expect(screen.queryByText('C:\\work\\demo')).not.toBeInTheDocument();
  });

  it('添加项目 action：选目录 → register → open → 进入新会话', async () => {
    (window as unknown as { electronAPI: unknown }).electronAPI = {
      selectDirectory: vi.fn().mockResolvedValue('C:\\work\\picked'),
    };
    projectRegisterMock.mockResolvedValue(projects[0]);
    projectOpenMock.mockResolvedValue({
      project: projects[0],
      session: {
        id: 's-new',
        title: 'demo',
        created_at: 1,
        updated_at: 1,
        last_message_at: null,
        message_count: 0,
        is_pinned: false,
      },
      created: true,
    });
    renderPalette();

    fireEvent.click(screen.getByText('添加项目'));

    await waitFor(() => {
      expect(projectRegisterMock).toHaveBeenCalledWith('C:\\work\\picked');
      expect(projectOpenMock).toHaveBeenCalledWith('p1');
      expect(useStore.getState().currentSessionId).toBe('s-new');
    });
  });

  // ===== P7: 搜索模式（>=2 字符）项目命中 =====

  it('P7: 搜索词命中项目名时渲染项目分组，点击走 projects_open', async () => {
    projectListMock.mockResolvedValue([]);
    mockBackendRequest.mockResolvedValue({
      projects: [{ id: 'p1', name: 'demo', path: 'C:\\work\\demo', session_count: 2 }],
    });
    projectOpenMock.mockResolvedValue({
      project: {
        id: 'p1',
        path: 'C:\\work\\demo',
        name: 'demo',
        createdAt: 1,
        lastOpenedAt: 1,
        sessionCount: 2,
        lastSessionId: null,
      },
      session: {
        id: 's-opened',
        title: 'demo',
        created_at: 1,
        updated_at: 1,
        last_message_at: null,
        message_count: 0,
        is_pinned: false,
      },
      created: false,
    });
    renderPalette();

    fireEvent.change(screen.getByPlaceholderText('输入命令或搜索...'), {
      target: { value: 'demo' },
    });

    await waitFor(() => {
      expect(screen.getByText('demo')).toBeInTheDocument();
      expect(screen.getByText('C:\\work\\demo')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('demo'));
    await waitFor(() => {
      expect(projectOpenMock).toHaveBeenCalledWith('p1');
      expect(useStore.getState().currentSessionId).toBe('s-opened');
    });
  });
});
