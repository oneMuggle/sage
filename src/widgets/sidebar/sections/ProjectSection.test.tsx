import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import type { ProjectMaterial, ProjectSummary } from '../../../shared/api/projectApi';
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
// ===== M3 测试夹具 =====
const updateMock = vi.fn();
const listMaterialsMock = vi.fn();
const addMaterialMock = vi.fn();
const removeMaterialMock = vi.fn();
const saveAnswerAsMaterialMock = vi.fn();

vi.mock('../../../shared/api/projectApi', () => ({
  projectApi: {
    list: (...args: unknown[]) => listMock(...args),
    register: (...args: unknown[]) => registerMock(...args),
    remove: (...args: unknown[]) => removeMock(...args),
    open: (...args: unknown[]) => openMock(...args),
    createSession: (...args: unknown[]) => createSessionMock(...args),
    listSessions: (...args: unknown[]) => listSessionsMock(...args),
    update: (...args: unknown[]) => updateMock(...args),
    listMaterials: (...args: unknown[]) => listMaterialsMock(...args),
    addMaterial: (...args: unknown[]) => addMaterialMock(...args),
    removeMaterial: (...args: unknown[]) => removeMaterialMock(...args),
    saveAnswerAsMaterial: (...args: unknown[]) => saveAnswerAsMaterialMock(...args),
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
    description: 'desc-p1',
    instructions: 'instr-p1',
  },
  {
    id: 'p2',
    path: 'C:\\work\\empty',
    name: 'empty',
    createdAt: 2,
    lastOpenedAt: 5,
    sessionCount: 0,
    lastSessionId: null,
  },
];

const materialsFixture: ProjectMaterial[] = [
  {
    id: 'm1',
    projectId: 'p1',
    sourceMessageId: null,
    contentHash: 'h1',
    content: 'ready content body',
    status: 'ready',
    wikiPagePath: '/wiki/m1.md',
    errorMessage: null,
    createdAt: 100,
  },
  {
    id: 'm2',
    projectId: 'p1',
    sourceMessageId: 'msg-42',
    contentHash: 'h2',
    content: 'pending body',
    status: 'pending_index',
    wikiPagePath: null,
    errorMessage: null,
    createdAt: 200,
  },
  {
    id: 'm3',
    projectId: 'p1',
    sourceMessageId: null,
    contentHash: 'h3',
    content: 'failed body',
    status: 'failed',
    wikiPagePath: null,
    errorMessage: 'index timeout',
    createdAt: 300,
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
      updateMock,
      listMaterialsMock,
      addMaterialMock,
      removeMaterialMock,
      saveAnswerAsMaterialMock,
    ].forEach((m) => m.mockReset());
    listMock.mockResolvedValue([]);
    listMaterialsMock.mockResolvedValue([]);
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

  // ===== M3: 项目概览面板 (description/instructions) =====

  it('M3: 展开项目 → 概览面板懒拉资料 + textarea 预填 description/instructions', async () => {
    listMock.mockResolvedValue(projects);
    listMaterialsMock.mockResolvedValue(materialsFixture);
    renderWithI18n(<ProjectSection {...baseProps} />);
    await waitFor(() => screen.getAllByTestId('project-row'));

    // 展开前资料/概览不渲染、不拉取
    expect(screen.queryByTestId('project-materials-panel')).not.toBeInTheDocument();
    expect(screen.queryByTestId('project-overview-panel')).not.toBeInTheDocument();
    expect(listMaterialsMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getAllByTestId('project-expand')[0]);
    await waitFor(() => {
      expect(screen.getByTestId('project-overview-panel')).toBeInTheDocument();
      expect(screen.getByTestId('project-materials-panel')).toBeInTheDocument();
      expect(listMaterialsMock).toHaveBeenCalledWith('p1');
    });

    // 预填项目元数据到 textarea
    const desc = screen.getByTestId('project-overview-description') as HTMLTextAreaElement;
    const instr = screen.getByTestId('project-overview-instructions') as HTMLTextAreaElement;
    expect(desc.value).toBe('desc-p1');
    expect(instr.value).toBe('instr-p1');

    // 初始：草稿干净 → 保存按钮 disabled
    expect(screen.getByTestId('project-overview-save')).toBeDisabled();
  });

  it('M3: 修改 description 后保存按钮可用 → 调用 update + 局部刷新清单', async () => {
    listMock.mockResolvedValue(projects);
    listMaterialsMock.mockResolvedValue([]);
    const updated: ProjectSummary = {
      ...projects[0],
      description: 'updated desc',
    };
    updateMock.mockResolvedValue(updated);
    renderWithI18n(<ProjectSection {...baseProps} />);
    await waitFor(() => screen.getAllByTestId('project-row'));

    fireEvent.click(screen.getAllByTestId('project-expand')[0]);
    await waitFor(() => screen.getByTestId('project-overview-description'));

    const desc = screen.getByTestId('project-overview-description');
    fireEvent.change(desc, { target: { value: 'updated desc' } });
    const saveBtn = screen.getByTestId('project-overview-save');
    expect(saveBtn).not.toBeDisabled();

    fireEvent.click(saveBtn);
    await waitFor(() => {
      expect(updateMock).toHaveBeenCalledWith('p1', {
        description: 'updated desc',
        instructions: 'instr-p1',
      });
    });
  });

  it('M3: 概览保存失败时 textarea 草稿保留不变（用户可重试）', async () => {
    listMock.mockResolvedValue(projects);
    listMaterialsMock.mockResolvedValue([]);
    updateMock.mockRejectedValue(new Error('server boom'));
    renderWithI18n(<ProjectSection {...baseProps} />);
    await waitFor(() => screen.getAllByTestId('project-row'));

    fireEvent.click(screen.getAllByTestId('project-expand')[0]);
    await waitFor(() => screen.getByTestId('project-overview-description'));

    fireEvent.change(screen.getByTestId('project-overview-description'), {
      target: { value: 'in-progress edit' },
    });
    fireEvent.click(screen.getByTestId('project-overview-save'));

    await waitFor(() => {
      expect(updateMock).toHaveBeenCalled();
    });
    // 草稿保留, button 仍可用（dirty 状态还在）
    const desc = screen.getByTestId('project-overview-description') as HTMLTextAreaElement;
    expect(desc.value).toBe('in-progress edit');
    expect(screen.getByTestId('project-overview-save')).not.toBeDisabled();
  });

  // ===== M3: 资料管理面板 (CRUD + status badge) =====

  it('M3: 资料面板按 wire status 渲染三个徽标 + ready 内容预览 + failed 错误', async () => {
    listMock.mockResolvedValue(projects);
    listMaterialsMock.mockResolvedValue(materialsFixture);
    renderWithI18n(<ProjectSection {...baseProps} />);
    await waitFor(() => screen.getAllByTestId('project-row'));

    fireEvent.click(screen.getAllByTestId('project-expand')[0]);
    await waitFor(() => screen.getAllByTestId('project-material-row'));

    expect(screen.getAllByTestId('project-material-row')).toHaveLength(3);
    expect(screen.getByTestId('project-material-status-ready')).toBeInTheDocument();
    expect(screen.getByTestId('project-material-status-pending_index')).toBeInTheDocument();
    expect(screen.getByTestId('project-material-status-failed')).toBeInTheDocument();
    // ready 内容截断展示 + failed error 展示
    expect(screen.getByText(/ready content body/)).toBeInTheDocument();
    expect(screen.getByTestId('project-material-error')).toHaveTextContent('index timeout');
  });

  it('M3: 粘贴文本 → 点添加 → 调用 addMaterial 并刷新清单（输入框清空）', async () => {
    listMock.mockResolvedValue(projects);
    listMaterialsMock.mockResolvedValueOnce([]).mockResolvedValueOnce([materialsFixture[0]]);
    addMaterialMock.mockResolvedValue(materialsFixture[0]);
    renderWithI18n(<ProjectSection {...baseProps} />);
    await waitFor(() => screen.getAllByTestId('project-row'));

    fireEvent.click(screen.getAllByTestId('project-expand')[0]);
    await waitFor(() => screen.getByTestId('project-material-input'));

    const input = screen.getByTestId('project-material-input');
    fireEvent.change(input, { target: { value: '粘贴的资料文本' } });

    const addBtn = screen.getByTestId('project-material-add');
    expect(addBtn).not.toBeDisabled();
    fireEvent.click(addBtn);

    await waitFor(() => {
      // addMaterial 调用只透传组件传入的字段，source_message_id 由 projectApi 在 invoke 时补 null
      expect(addMaterialMock).toHaveBeenCalledWith('p1', {
        content: '粘贴的资料文本',
      });
      expect(listMaterialsMock).toHaveBeenCalledTimes(2);
    });
    // 输入框已清空
    expect((screen.getByTestId('project-material-input') as HTMLTextAreaElement).value).toBe('');
  });

  it('M3: 空文本不允许添加（按钮 disabled）', async () => {
    listMock.mockResolvedValue(projects);
    listMaterialsMock.mockResolvedValue([]);
    renderWithI18n(<ProjectSection {...baseProps} />);
    await waitFor(() => screen.getAllByTestId('project-row'));

    fireEvent.click(screen.getAllByTestId('project-expand')[0]);
    await waitFor(() => screen.getByTestId('project-material-input'));

    const addBtn = screen.getByTestId('project-material-add');
    // 仅含空白也视为空
    fireEvent.change(screen.getByTestId('project-material-input'), { target: { value: '   ' } });
    expect(addBtn).toBeDisabled();

    // 空白不应触发 addMaterial 调用
    fireEvent.click(addBtn);
    await new Promise((r) => setTimeout(r, 50));
    expect(addMaterialMock).not.toHaveBeenCalled();
  });

  it('M3: 资料超 1 MiB → 拒绝添加（前端拦截，不发请求）', async () => {
    listMock.mockResolvedValue(projects);
    listMaterialsMock.mockResolvedValue([]);
    renderWithI18n(<ProjectSection {...baseProps} />);
    await waitFor(() => screen.getAllByTestId('project-row'));

    fireEvent.click(screen.getAllByTestId('project-expand')[0]);
    await waitFor(() => screen.getByTestId('project-material-input'));

    // 1 MiB + 1 字符
    const oversized = 'x'.repeat(1_000_001);
    fireEvent.change(screen.getByTestId('project-material-input'), {
      target: { value: oversized },
    });

    const addBtn = screen.getByTestId('project-material-add');
    expect(addBtn).not.toBeDisabled(); // disabled 仅基于空文本判定
    fireEvent.click(addBtn);

    await new Promise((r) => setTimeout(r, 50));
    expect(addMaterialMock).not.toHaveBeenCalled();
  });

  it('M3: 资料删除按钮 → 调用 removeMaterial 并就地移除该行', async () => {
    listMock.mockResolvedValue(projects);
    listMaterialsMock.mockResolvedValue(materialsFixture);
    removeMaterialMock.mockResolvedValue(true);
    renderWithI18n(<ProjectSection {...baseProps} />);
    await waitFor(() => screen.getAllByTestId('project-row'));

    fireEvent.click(screen.getAllByTestId('project-expand')[0]);
    await waitFor(() => screen.getAllByTestId('project-material-row'));

    expect(screen.getAllByTestId('project-material-row')).toHaveLength(3);
    fireEvent.click(screen.getAllByTestId('project-material-remove')[0]); // m1

    await waitFor(() => {
      expect(removeMaterialMock).toHaveBeenCalledWith('p1', 'm1');
      expect(screen.getAllByTestId('project-material-row')).toHaveLength(2);
    });
  });

  // ===== M3: 保存回答入口 =====

  it('M3: 当前会话无 active → 保存回答按钮 disabled', async () => {
    listMock.mockResolvedValue(projects);
    listMaterialsMock.mockResolvedValue([]);
    useStore.setState({ currentSessionId: null, messages: [] });
    renderWithI18n(<ProjectSection {...baseProps} />);
    await waitFor(() => screen.getAllByTestId('project-row'));

    fireEvent.click(screen.getAllByTestId('project-expand')[0]);
    await waitFor(() => screen.getByTestId('project-save-answer'));

    expect(screen.getByTestId('project-save-answer')).toBeDisabled();
  });

  it('M3: 有 active 会话 + 最后一条 assistant 消息 → 保存为资料', async () => {
    listMock.mockResolvedValue(projects);
    listMaterialsMock.mockResolvedValueOnce([]).mockResolvedValueOnce([
      materialsFixture[1], // pending
    ]);
    saveAnswerAsMaterialMock.mockResolvedValue(materialsFixture[1]);

    useStore.setState({
      currentSessionId: 's-active',
      messages: [
        { id: 'user-1', role: 'user', content: 'hi', createdAt: 1 } as never,
        { id: 'asst-1', role: 'assistant', content: 'first', createdAt: 2 } as never,
        { id: 'user-2', role: 'user', content: 'follow up', createdAt: 3 } as never,
        { id: 'asst-2', role: 'assistant', content: 'final answer', createdAt: 4 } as never,
      ],
    });

    renderWithI18n(<ProjectSection {...baseProps} />);
    await waitFor(() => screen.getAllByTestId('project-row'));

    fireEvent.click(screen.getAllByTestId('project-expand')[0]);
    await waitFor(() => screen.getByTestId('project-save-answer'));

    const saveBtn = screen.getByTestId('project-save-answer');
    expect(saveBtn).not.toBeDisabled();
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(saveAnswerAsMaterialMock).toHaveBeenCalledWith('p1', 'asst-2');
      expect(listMaterialsMock).toHaveBeenCalledTimes(2);
    });
  });

  it('M3: 当前会话只有 user 消息 → 保存按钮点击给出"无 AI 回答"提示', async () => {
    listMock.mockResolvedValue(projects);
    listMaterialsMock.mockResolvedValue([]);
    useStore.setState({
      currentSessionId: 's-active',
      messages: [{ id: 'u1', role: 'user', content: 'only user', createdAt: 1 } as never],
    });

    renderWithI18n(<ProjectSection {...baseProps} />);
    await waitFor(() => screen.getAllByTestId('project-row'));

    fireEvent.click(screen.getAllByTestId('project-expand')[0]);
    await waitFor(() => screen.getByTestId('project-save-answer'));

    fireEvent.click(screen.getByTestId('project-save-answer'));
    await new Promise((r) => setTimeout(r, 50));
    expect(saveAnswerAsMaterialMock).not.toHaveBeenCalled();
  });

  it('M3: 保存回答返回 403 (会话不属于该项目) → 不修改本地资料列表', async () => {
    listMock.mockResolvedValue(projects);
    listMaterialsMock.mockResolvedValue([]);
    saveAnswerAsMaterialMock.mockRejectedValue(
      Object.assign(new Error('mismatch'), { status_code: 403 }),
    );

    useStore.setState({
      currentSessionId: 's-active',
      messages: [{ id: 'asst-1', role: 'assistant', content: 'x', createdAt: 1 } as never],
    });

    renderWithI18n(<ProjectSection {...baseProps} />);
    await waitFor(() => screen.getAllByTestId('project-row'));

    fireEvent.click(screen.getAllByTestId('project-expand')[0]);
    await waitFor(() => screen.getByTestId('project-save-answer'));

    fireEvent.click(screen.getByTestId('project-save-answer'));
    await waitFor(() => {
      expect(saveAnswerAsMaterialMock).toHaveBeenCalledWith('p1', 'asst-1');
    });
    // 失败 → 不触发 refreshMaterials（用 listMaterialsMock 调用次数判定）
    await new Promise((r) => setTimeout(r, 50));
    expect(listMaterialsMock).toHaveBeenCalledTimes(1); // 仅首次拉取
  });
});
