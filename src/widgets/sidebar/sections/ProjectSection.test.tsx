import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import type { ProjectSummary } from '../../../shared/api/projectApi';
import { I18nProvider } from '../../../shared/lib/i18n';
import { useStore } from '../../../shared/lib/store';

import { ProjectSection } from './ProjectSection';

const listMock = vi.fn();
const registerMock = vi.fn();
const removeMock = vi.fn();
const openMock = vi.fn();
const createSessionMock = vi.fn();
const listSessionsMock = vi.fn();
const deleteSessionMock = vi.fn();
const updateAllowedPathsMock = vi.fn();

vi.mock('../../../shared/api/projectApi', () => ({
  projectApi: {
    list: (...args: unknown[]) => listMock(...args),
    register: (...args: unknown[]) => registerMock(...args),
    remove: (...args: unknown[]) => removeMock(...args),
    open: (...args: unknown[]) => openMock(...args),
    createSession: (...args: unknown[]) => createSessionMock(...args),
    listSessions: (...args: unknown[]) => listSessionsMock(...args),
    updateAllowedPaths: (...args: unknown[]) => updateAllowedPathsMock(...args),
  },
}));

vi.mock('../../../shared/api/sessionApi', () => ({
  sessionApi: {
    delete: (...args: unknown[]) => deleteSessionMock(...args),
  },
}));

const projects: ProjectSummary[] = [
  {
    id: 'p1',
    path: 'C:\\work\\demo',
    name: 'demo',
    createdAt: 1,
    lastOpenedAt: 10,
    sessionCount: 2,
    lastSessionId: 's1',
    allowedPaths: ['~/Documents/**'],
  },
  {
    id: 'p2',
    path: 'C:\\work\\empty',
    name: 'empty',
    createdAt: 2,
    lastOpenedAt: 5,
    sessionCount: 0,
    lastSessionId: null,
    allowedPaths: [],
  },
];

const session = {
  id: 's-new',
  title: 'demo',
  created_at: 1,
  updated_at: 1,
  last_message_at: null,
  message_count: 0,
  is_pinned: false,
};

const renderWithI18n = (ui: React.ReactNode) => render(<I18nProvider>{ui}</I18nProvider>);

const baseProps = {
  collapsed: false,
  onToggleCollapsed: () => {},
  onOpenSession: vi.fn(),
};

describe('ProjectSection', () => {
  beforeEach(() => {
    [
      listMock,
      registerMock,
      removeMock,
      openMock,
      createSessionMock,
      listSessionsMock,
      deleteSessionMock,
      updateAllowedPathsMock,
    ].forEach((m) => m.mockReset());
    listMock.mockResolvedValue([]);
  });

  it('renders section label and empty state', async () => {
    renderWithI18n(<ProjectSection {...baseProps} />);
    expect(screen.getByText('项目')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId('project-empty')).toBeInTheDocument();
    });
  });

  it('lists registered projects with name, path and session count', async () => {
    listMock.mockResolvedValue(projects);
    renderWithI18n(<ProjectSection {...baseProps} />);
    await waitFor(() => {
      expect(screen.getAllByTestId('project-row')).toHaveLength(2);
    });
    expect(screen.getByText('demo')).toBeInTheDocument();
    expect(screen.getByText('C:\\work\\demo')).toBeInTheDocument();
    // sessionCount=2 的项目显示计数徽标；0 不显示
    expect(screen.getByText('2')).toBeInTheDocument();
    expect(screen.queryByText('0')).not.toBeInTheDocument();
  });

  it('clicking a project row opens its session and notifies onOpenSession', async () => {
    listMock.mockResolvedValue(projects);
    openMock.mockResolvedValue({ project: projects[0], session, created: false });
    const onOpenSession = vi.fn();
    renderWithI18n(<ProjectSection {...baseProps} onOpenSession={onOpenSession} />);

    await waitFor(() => screen.getAllByTestId('project-row'));
    fireEvent.click(screen.getAllByTestId('project-row')[0]);

    await waitFor(() => {
      expect(openMock).toHaveBeenCalledWith('p1');
      expect(onOpenSession).toHaveBeenCalledWith('s-new');
    });
  });

  it('hover "+" creates a new bound session in the project', async () => {
    listMock.mockResolvedValue(projects);
    createSessionMock.mockResolvedValue({ project: projects[0], session });
    renderWithI18n(<ProjectSection {...baseProps} />);

    await waitFor(() => screen.getAllByTestId('project-row'));
    fireEvent.click(screen.getAllByTestId('project-new-chat')[0]);

    await waitFor(() => {
      expect(createSessionMock).toHaveBeenCalledWith('p1');
      expect(baseProps.onOpenSession).toHaveBeenCalledWith('s-new');
    });
  });

  it('TwoStepDelete: second click removes the project from the list', async () => {
    listMock.mockResolvedValue(projects);
    removeMock.mockResolvedValue(true);
    renderWithI18n(<ProjectSection {...baseProps} />);

    await waitFor(() => screen.getAllByTestId('project-row'));
    const removeBtn = screen.getAllByTestId('project-remove')[0];
    fireEvent.click(removeBtn); // 进入 armed
    expect(removeMock).not.toHaveBeenCalled();
    fireEvent.click(removeBtn); // 确认移除
    await waitFor(() => {
      expect(removeMock).toHaveBeenCalledWith('p1');
    });
  });

  it('add button picks a directory via IPC then registers and opens it', async () => {
    const selectDirectory = vi.fn().mockResolvedValue('C:\\work\\picked');
    (window as unknown as { electronAPI: unknown }).electronAPI = { selectDirectory };
    try {
      registerMock.mockResolvedValue(projects[0]);
      openMock.mockResolvedValue({ project: projects[0], session, created: true });
      renderWithI18n(<ProjectSection {...baseProps} />);

      await waitFor(() => screen.getByTestId('project-add-button'));
      fireEvent.click(screen.getByTestId('project-add-button'));

      await waitFor(() => {
        expect(selectDirectory).toHaveBeenCalledWith({ intent: 'open' });
        expect(registerMock).toHaveBeenCalledWith('C:\\work\\picked');
        expect(openMock).toHaveBeenCalledWith('p1');
        expect(baseProps.onOpenSession).toHaveBeenCalledWith('s-new');
      });
    } finally {
      delete (window as unknown as { electronAPI?: unknown }).electronAPI;
    }
  });

  it('marks a project as missing when open returns 410', async () => {
    listMock.mockResolvedValue(projects);
    openMock.mockRejectedValue(Object.assign(new Error('gone'), { status_code: 410 }));
    renderWithI18n(<ProjectSection {...baseProps} />);

    await waitFor(() => screen.getAllByTestId('project-row'));
    fireEvent.click(screen.getAllByTestId('project-row')[0]);

    await waitFor(() => {
      expect(screen.getByTestId('project-missing-badge')).toBeInTheDocument();
    });
  });

  // ===== P2: 行展开会话子列表 =====

  it('P2: 展开 chevron 懒加载会话子列表，子行点击切换会话', async () => {
    listMock.mockResolvedValue(projects);
    listSessionsMock.mockResolvedValue([
      { ...session, id: 's1', title: 'first session', updated_at: Date.now() },
      { ...session, id: 's2', title: 'second session', updated_at: Date.now() },
    ]);
    const onOpenSession = vi.fn();
    renderWithI18n(<ProjectSection {...baseProps} onOpenSession={onOpenSession} />);

    await waitFor(() => screen.getAllByTestId('project-row'));
    expect(screen.queryByTestId('project-session-row')).not.toBeInTheDocument();

    // 展开第一个项目
    fireEvent.click(screen.getAllByTestId('project-expand')[0]);
    await waitFor(() => {
      expect(listSessionsMock).toHaveBeenCalledWith('p1');
      expect(screen.getAllByTestId('project-session-row')).toHaveLength(2);
    });
    expect(screen.getByText('first session')).toBeInTheDocument();

    // 子行点击 → onOpenSession（不触发行点击的 open）
    fireEvent.click(screen.getAllByTestId('project-session-row')[0]);
    await waitFor(() => {
      expect(onOpenSession).toHaveBeenCalledWith('s1');
    });
    expect(openMock).not.toHaveBeenCalled();
  });

  it('P2: 展开无会话的项目显示空态提示', async () => {
    listMock.mockResolvedValue(projects);
    listSessionsMock.mockResolvedValue([]);
    renderWithI18n(<ProjectSection {...baseProps} />);

    await waitFor(() => screen.getAllByTestId('project-row'));
    fireEvent.click(screen.getAllByTestId('project-expand')[1]); // empty 项目

    await waitFor(() => {
      expect(screen.getByTestId('project-sessions-empty')).toBeInTheDocument();
    });
  });

  it('P2: 再次点击 chevron 收起子列表', async () => {
    listMock.mockResolvedValue(projects);
    listSessionsMock.mockResolvedValue([{ ...session, id: 's1', title: 'first session' }]);
    renderWithI18n(<ProjectSection {...baseProps} />);

    await waitFor(() => screen.getAllByTestId('project-row'));
    fireEvent.click(screen.getAllByTestId('project-expand')[0]);
    await waitFor(() => {
      expect(screen.getAllByTestId('project-session-row').length).toBe(1);
    });

    fireEvent.click(screen.getAllByTestId('project-expand')[0]);
    await waitFor(() => {
      expect(screen.queryByTestId('project-session-row')).not.toBeInTheDocument();
    });
    // 收起再展开不重复拉取（缓存命中）
    fireEvent.click(screen.getAllByTestId('project-expand')[0]);
    await waitFor(() => {
      expect(screen.getAllByTestId('project-session-row').length).toBe(1);
    });
    expect(listSessionsMock).toHaveBeenCalledTimes(1);
  });

  // ===== P4: 子行会话删除 + 会话数量联动刷新 =====

  it('P4: 子行删除两步确认后调用 sessionApi.delete 并刷新清单/子列表', async () => {
    listMock.mockResolvedValue(projects);
    listSessionsMock.mockResolvedValue([{ ...session, id: 's1', title: 'first session' }]);
    deleteSessionMock.mockResolvedValue(undefined);
    renderWithI18n(<ProjectSection {...baseProps} />);

    await waitFor(() => screen.getAllByTestId('project-row'));
    fireEvent.click(screen.getAllByTestId('project-expand')[0]);
    await waitFor(() => screen.getAllByTestId('project-session-row'));

    const callsBefore = listMock.mock.calls.length;
    const delBtn = screen.getAllByTestId('project-session-delete')[0];
    fireEvent.click(delBtn); // armed
    expect(deleteSessionMock).not.toHaveBeenCalled();
    fireEvent.click(delBtn); // 确认
    await waitFor(() => {
      expect(deleteSessionMock).toHaveBeenCalledWith('s1');
      // 删除联动刷新项目清单（计数）与子列表
      expect(listMock.mock.calls.length).toBeGreaterThan(callsBefore);
      expect(listSessionsMock).toHaveBeenCalledTimes(2);
    });
  });

  it('P4: 子行删除失败时保留子列表并提示', async () => {
    listMock.mockResolvedValue(projects);
    listSessionsMock.mockResolvedValue([{ ...session, id: 's1', title: 'first session' }]);
    deleteSessionMock.mockRejectedValue(new Error('backend offline'));
    renderWithI18n(<ProjectSection {...baseProps} />);

    await waitFor(() => screen.getAllByTestId('project-row'));
    fireEvent.click(screen.getAllByTestId('project-expand')[0]);
    await waitFor(() => screen.getAllByTestId('project-session-row'));

    const delBtn = screen.getAllByTestId('project-session-delete')[0];
    fireEvent.click(delBtn);
    fireEvent.click(delBtn);
    await waitFor(() => {
      expect(deleteSessionMock).toHaveBeenCalledWith('s1');
    });
    // 失败不收起子列表
    expect(screen.getAllByTestId('project-session-row').length).toBe(1);
  });

  it('P4: store 会话数量变化触发项目清单防抖刷新', async () => {
    vi.useFakeTimers();
    try {
      listMock.mockResolvedValue([]);
      renderWithI18n(<ProjectSection {...baseProps} />);
      await vi.advanceTimersByTimeAsync(0);
      const initialCalls = listMock.mock.calls.length;
      expect(initialCalls).toBeGreaterThan(0);

      useStore.setState({ sessions: [{ ...session, id: 'sx', title: 'x' }] });
      await vi.advanceTimersByTimeAsync(500);

      expect(listMock.mock.calls.length).toBeGreaterThan(initialCalls);
    } finally {
      vi.useRealTimers();
    }
  });

  // ===== P5: 区块局部拖拽登记 =====

  it('P5: 拖入带 path 的文件 → 批量登记并刷新清单', async () => {
    listMock.mockResolvedValue([]);
    renderWithI18n(<ProjectSection {...baseProps} />);
    await waitFor(() => screen.getByTestId('project-drop-zone'));

    const callsBefore = listMock.mock.calls.length;
    fireEvent.drop(screen.getByTestId('project-drop-zone'), {
      dataTransfer: {
        files: [{ path: 'C:\\work\\a' }, { path: 'C:\\work\\b' }],
      } as unknown as DataTransfer,
    });

    await waitFor(() => {
      expect(registerMock).toHaveBeenCalledTimes(2);
      expect(registerMock).toHaveBeenCalledWith('C:\\work\\a');
      expect(listMock.mock.calls.length).toBeGreaterThan(callsBefore);
    });
  });

  it('P5: 拖入无 path 的文件（浏览器语义）静默忽略', async () => {
    listMock.mockResolvedValue([]);
    renderWithI18n(<ProjectSection {...baseProps} />);
    await waitFor(() => screen.getByTestId('project-drop-zone'));

    const callsBefore = registerMock.mock.calls.length;
    fireEvent.drop(screen.getByTestId('project-drop-zone'), {
      dataTransfer: { files: [{ name: 'x.txt' }] } as unknown as DataTransfer,
    });

    // 异步 handler 有机会执行后仍不应调用 register
    await new Promise((r) => setTimeout(r, 50));
    expect(registerMock.mock.calls.length).toBe(callsBefore);
  });

  it('P5: dragOver 显示提示、dragLeave 复位', async () => {
    listMock.mockResolvedValue([]);
    renderWithI18n(<ProjectSection {...baseProps} />);
    const zone = screen.getByTestId('project-drop-zone');

    expect(screen.queryByTestId('project-drop-hint')).not.toBeInTheDocument();
    fireEvent.dragOver(zone, { dataTransfer: { files: [] } });
    expect(screen.getByTestId('project-drop-hint')).toBeInTheDocument();

    fireEvent.dragLeave(zone, { dataTransfer: { files: [] } });
    expect(screen.queryByTestId('project-drop-hint')).not.toBeInTheDocument();
  });

  it('P5: register 失败（非目录）时逐条提示且不刷新清单', async () => {
    listMock.mockResolvedValue([]);
    registerMock.mockRejectedValue(
      new Error('Backend POST /api/v1/projects → 400: invalid_workspace_path'),
    );
    renderWithI18n(<ProjectSection {...baseProps} />);
    await waitFor(() => screen.getByTestId('project-drop-zone'));

    const callsBefore = listMock.mock.calls.length;
    fireEvent.drop(screen.getByTestId('project-drop-zone'), {
      dataTransfer: { files: [{ path: 'C:\\not-a-dir' }] } as unknown as DataTransfer,
    });

    await waitFor(() => {
      expect(registerMock).toHaveBeenCalledWith('C:\\not-a-dir');
    });
    // 全部失败：清单不刷新
    await new Promise((r) => setTimeout(r, 50));
    expect(listMock.mock.calls.length).toBe(callsBefore);
  });

  // ===== P1 (2026-09-17): allowed_paths 内联编辑器 =====

  it('P1: 展开后展示 allowed_paths 只读列表与编辑按钮', async () => {
    listMock.mockResolvedValue(projects);
    renderWithI18n(<ProjectSection {...baseProps} />);
    await waitFor(() => screen.getAllByTestId('project-row'));

    // 展开第一个项目（已有规则）
    fireEvent.click(screen.getAllByTestId('project-expand')[0]);
    await waitFor(() => {
      expect(screen.getByTestId('allowed-paths-editor')).toBeInTheDocument();
    });
    // p1 已有规则 '~/Documents/**'
    const editors = screen.getAllByTestId('allowed-paths-list');
    expect(editors[0].textContent).toContain('~/Documents/**');
    // 编辑按钮存在
    expect(screen.getAllByTestId('allowed-paths-edit')[0]).toBeInTheDocument();
  });

  it('P1: 展开空规则的第二个项目显示空态提示', async () => {
    listMock.mockResolvedValue(projects);
    renderWithI18n(<ProjectSection {...baseProps} />);
    await waitFor(() => screen.getAllByTestId('project-row'));

    fireEvent.click(screen.getAllByTestId('project-expand')[1]); // p2: allowedPaths=[]
    await waitFor(() => {
      const empties = screen.getAllByTestId('allowed-paths-empty');
      expect(empties.length).toBeGreaterThan(0);
    });
  });

  it('P1: 编辑态输入新规则 → Add 加入草稿 → Save 调用 updateAllowedPaths', async () => {
    listMock.mockResolvedValue(projects);
    updateAllowedPathsMock.mockResolvedValue(['~/Documents/**', '~/Desktop/**']);
    renderWithI18n(<ProjectSection {...baseProps} />);
    await waitFor(() => screen.getAllByTestId('project-row'));

    fireEvent.click(screen.getAllByTestId('project-expand')[1]); // p2: 空规则
    await waitFor(() => screen.getByTestId('allowed-paths-edit'));

    fireEvent.click(screen.getAllByTestId('allowed-paths-edit')[0]);
    await waitFor(() => screen.getByTestId('allowed-paths-input'));

    const input = screen.getByTestId('allowed-paths-input');
    fireEvent.change(input, { target: { value: '~/Desktop/**' } });
    fireEvent.click(screen.getAllByTestId('allowed-paths-add')[0]);

    await waitFor(() => {
      expect(screen.getAllByTestId('allowed-paths-row')).toHaveLength(1);
      expect(screen.getByTestId('allowed-paths-row').textContent).toContain('~/Desktop/**');
    });

    fireEvent.click(screen.getByTestId('allowed-paths-save'));
    await waitFor(() => {
      expect(updateAllowedPathsMock).toHaveBeenCalledWith('p2', ['~/Desktop/**']);
    });
  });

  it('P1: Save 失败保留编辑态并提示', async () => {
    listMock.mockResolvedValue(projects);
    updateAllowedPathsMock.mockRejectedValue(new Error('backend offline'));
    renderWithI18n(<ProjectSection {...baseProps} />);
    await waitFor(() => screen.getAllByTestId('project-row'));

    fireEvent.click(screen.getAllByTestId('project-expand')[0]);
    await waitFor(() => screen.getByTestId('allowed-paths-edit'));
    fireEvent.click(screen.getAllByTestId('allowed-paths-edit')[0]);
    await waitFor(() => screen.getByTestId('allowed-paths-save'));

    fireEvent.click(screen.getByTestId('allowed-paths-save'));
    await waitFor(() => {
      expect(updateAllowedPathsMock).toHaveBeenCalled();
      // 编辑态保留：input 仍在
      expect(screen.getByTestId('allowed-paths-input')).toBeInTheDocument();
    });
  });

  it('P1: Cancel 退出编辑态且不调用 updateAllowedPaths', async () => {
    listMock.mockResolvedValue(projects);
    renderWithI18n(<ProjectSection {...baseProps} />);
    await waitFor(() => screen.getAllByTestId('project-row'));

    fireEvent.click(screen.getAllByTestId('project-expand')[0]);
    await waitFor(() => screen.getByTestId('allowed-paths-edit'));
    fireEvent.click(screen.getAllByTestId('allowed-paths-edit')[0]);
    await waitFor(() => screen.getByTestId('allowed-paths-cancel'));

    fireEvent.click(screen.getByTestId('allowed-paths-cancel'));
    await waitFor(() => {
      expect(screen.queryByTestId('allowed-paths-cancel')).not.toBeInTheDocument();
      expect(updateAllowedPathsMock).not.toHaveBeenCalled();
    });
  });
});
