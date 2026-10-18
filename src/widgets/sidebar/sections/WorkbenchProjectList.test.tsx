// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ProjectMaterial, ProjectSummary } from '../../../shared/api/projectApi';
import { I18nProvider } from '../../../shared/lib/i18n';
import { useStore } from '../../../shared/lib/store';

import { WorkbenchProjectList } from './WorkbenchProjectList';

/* ── Mock API surface ─────────────────────────────────────────────── */

const listMock = vi.fn();
const registerMock = vi.fn();
const removeMock = vi.fn();
const openMock = vi.fn();
const createSessionMock = vi.fn();
const listSessionsMock = vi.fn();
const deleteSessionMock = vi.fn();
const updateMock = vi.fn();
const listMaterialsMock = vi.fn();
const addMaterialMock = vi.fn();
const removeMaterialMock = vi.fn();
const saveAnswerAsMaterialMock = vi.fn();
const updateMaterialMock = vi.fn();

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
    updateMaterial: (...args: unknown[]) => updateMaterialMock(...args),
  },
}));

vi.mock('../../../shared/api/sessionApi', () => ({
  sessionApi: {
    delete: (...args: unknown[]) => deleteSessionMock(...args),
  },
}));

/* ── Fixtures ─────────────────────────────────────────────────────── */

const projects: ProjectSummary[] = [
  {
    id: 'p1',
    path: 'C:\\work\\demo',
    name: 'demo',
    createdAt: 1,
    lastOpenedAt: 10,
    allowedPaths: [],
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
    allowedPaths: [],
    sessionCount: 0,
    lastSessionId: null,
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

const materialsFixture: ProjectMaterial[] = [
  {
    id: 'mat-1',
    projectId: 'p1',
    sourceMessageId: null,
    contentHash: 'abc123',
    content: '# Reference',
    status: 'ready',
    wikiPagePath: null,
    errorMessage: null,
    createdAt: 1,
    enabled: true,
  },
];

/* ── Helpers ──────────────────────────────────────────────────────── */

const renderWithI18n = (ui: React.ReactNode) => render(<I18nProvider>{ui}</I18nProvider>);

const onOpenSession = vi.fn();

/* ── Tests ────────────────────────────────────────────────────────── */

describe('WorkbenchProjectList', () => {
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
      updateMaterialMock,
    ].forEach((m) => m.mockReset());
    listMock.mockResolvedValue([]);
    listMaterialsMock.mockResolvedValue([]);
    onOpenSession.mockReset();
    useStore.setState({ currentSessionId: null, sessions: [] });
  });

  /* ── Basic rendering ──────────────────────────────────────────── */

  it('renders section header and empty state', async () => {
    renderWithI18n(<WorkbenchProjectList onOpenSession={onOpenSession} />);
    expect(screen.getByText('项目')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId('project-empty')).toBeInTheDocument();
    });
  });

  it('lists registered projects with name, path and session count', async () => {
    listMock.mockResolvedValue(projects);
    renderWithI18n(<WorkbenchProjectList onOpenSession={onOpenSession} />);
    await waitFor(() => {
      expect(screen.getAllByTestId('project-row')).toHaveLength(2);
    });
    expect(screen.getByText('demo')).toBeInTheDocument();
    expect(screen.getByText('C:\\work\\demo')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
    expect(screen.queryByText('0')).not.toBeInTheDocument();
  });

  /* ── Click → toggleExpand (not openProject) ──────────────────── */

  it('clicking a project row toggles expand (not openProject)', async () => {
    listMock.mockResolvedValue(projects);
    renderWithI18n(<WorkbenchProjectList onOpenSession={onOpenSession} />);

    await waitFor(() => screen.getAllByTestId('project-row'));
    fireEvent.click(screen.getAllByTestId('project-row')[0]);

    // Workbench: row click → expand, NOT openProject
    await waitFor(() => {
      expect(openMock).not.toHaveBeenCalled();
    });
    // Sub-sessions should load (expand behavior)
    await waitFor(() => {
      expect(listSessionsMock).toHaveBeenCalledWith('p1');
    });
  });

  /* ── Hover "+" creates session ────────────────────────────────── */

  it('hover "+" creates a new bound session in the project', async () => {
    listMock.mockResolvedValue(projects);
    createSessionMock.mockResolvedValue({ project: projects[0], session });
    renderWithI18n(<WorkbenchProjectList onOpenSession={onOpenSession} />);

    await waitFor(() => screen.getAllByTestId('project-row'));
    fireEvent.click(screen.getAllByTestId('project-new-chat')[0]);

    await waitFor(() => {
      expect(createSessionMock).toHaveBeenCalledWith('p1');
      expect(onOpenSession).toHaveBeenCalledWith('s-new');
    });
  });

  /* ── TwoStepDelete ────────────────────────────────────────────── */

  it('TwoStepDelete: second click removes the project from the list', async () => {
    listMock.mockResolvedValue(projects);
    removeMock.mockResolvedValue(true);
    renderWithI18n(<WorkbenchProjectList onOpenSession={onOpenSession} />);

    await waitFor(() => screen.getAllByTestId('project-row'));
    const removeBtn = screen.getAllByTestId('project-remove')[0];
    fireEvent.click(removeBtn);
    expect(removeMock).not.toHaveBeenCalled();
    fireEvent.click(removeBtn);
    await waitFor(() => {
      expect(removeMock).toHaveBeenCalledWith('p1');
    });
  });

  /* ── Add button ───────────────────────────────────────────────── */

  it('add button picks a directory via IPC then registers it', async () => {
    const selectDirectory = vi.fn().mockResolvedValue('C:\\work\\picked');
    (window as unknown as { electronAPI: unknown }).electronAPI = { selectDirectory };
    try {
      registerMock.mockResolvedValue(projects[0]);
      openMock.mockResolvedValue({ project: projects[0], session, created: true });
      renderWithI18n(<WorkbenchProjectList onOpenSession={onOpenSession} />);

      await waitFor(() => screen.getByTestId('project-add-button'));
      fireEvent.click(screen.getByTestId('project-add-button'));

      await waitFor(() => {
        expect(selectDirectory).toHaveBeenCalledWith({ intent: 'open' });
        expect(registerMock).toHaveBeenCalledWith('C:\\work\\picked');
      });
    } finally {
      delete (window as unknown as { electronAPI?: unknown }).electronAPI;
    }
  });

  /* ── Missing badge ────────────────────────────────────────────── */

  it('marks a project as missing when createSession returns 410', async () => {
    listMock.mockResolvedValue(projects);
    createSessionMock.mockRejectedValue(Object.assign(new Error('gone'), { status_code: 410 }));
    renderWithI18n(<WorkbenchProjectList onOpenSession={onOpenSession} />);

    await waitFor(() => screen.getAllByTestId('project-row'));
    // In workbench: "new chat" calls handleNewChatInProject → createSession
    fireEvent.click(screen.getAllByTestId('project-new-chat')[0]);

    await waitFor(() => {
      expect(screen.getByTestId('project-missing-badge')).toBeInTheDocument();
    });
  });

  /* ── Sub-sessions ─────────────────────────────────────────────── */

  it('expand chevron loads sub-sessions; click sub-row → onOpenSession', async () => {
    listMock.mockResolvedValue(projects);
    listSessionsMock.mockResolvedValue([
      { ...session, id: 's1', title: 'first session', updated_at: Date.now() },
      { ...session, id: 's2', title: 'second session', updated_at: Date.now() },
    ]);
    renderWithI18n(<WorkbenchProjectList onOpenSession={onOpenSession} />);

    await waitFor(() => screen.getAllByTestId('project-row'));
    fireEvent.click(screen.getAllByTestId('project-expand')[0]);
    await waitFor(() => {
      expect(listSessionsMock).toHaveBeenCalledWith('p1');
      expect(screen.getAllByTestId('project-session-row')).toHaveLength(2);
    });

    fireEvent.click(screen.getAllByTestId('project-session-row')[0]);
    await waitFor(() => {
      expect(onOpenSession).toHaveBeenCalledWith('s1');
    });
  });

  it('expand empty project shows empty sub-sessions message', async () => {
    listMock.mockResolvedValue(projects);
    listSessionsMock.mockResolvedValue([]);
    renderWithI18n(<WorkbenchProjectList onOpenSession={onOpenSession} />);

    await waitFor(() => screen.getAllByTestId('project-row'));
    fireEvent.click(screen.getAllByTestId('project-expand')[1]);

    await waitFor(() => {
      expect(screen.getByTestId('project-sessions-empty')).toBeInTheDocument();
    });
  });

  /* ── Stage badge ──────────────────────────────────────────────── */

  it('renders localized project stage pill when projectStage is set', async () => {
    listMock.mockResolvedValue([
      {
        ...projects[0],
        projectType: 'business',
        projectStage: 'initiation',
      },
    ]);
    renderWithI18n(<WorkbenchProjectList onOpenSession={onOpenSession} />);
    const stageBadge = await screen.findByTestId('project-row-stage-badge');
    expect(stageBadge).toHaveTextContent('立卷归集');
  });

  /* ── Drag-drop ────────────────────────────────────────────────── */

  it('drag-drop with path files registers them', async () => {
    listMock.mockResolvedValue([]);
    renderWithI18n(<WorkbenchProjectList onOpenSession={onOpenSession} />);
    await waitFor(() => screen.getByTestId('project-drop-zone'));

    fireEvent.drop(screen.getByTestId('project-drop-zone'), {
      dataTransfer: {
        files: [{ path: 'C:\\work\\a' }, { path: 'C:\\work\\b' }],
      } as unknown as DataTransfer,
    });

    await waitFor(() => {
      expect(registerMock).toHaveBeenCalledTimes(2);
      expect(registerMock).toHaveBeenCalledWith('C:\\work\\a');
    });
  });

  it('dragOver shows hint, dragLeave resets', async () => {
    listMock.mockResolvedValue([]);
    renderWithI18n(<WorkbenchProjectList onOpenSession={onOpenSession} />);
    const zone = screen.getByTestId('project-drop-zone');

    expect(screen.queryByTestId('project-drop-hint')).not.toBeInTheDocument();
    fireEvent.dragOver(zone, { dataTransfer: { files: [] } });
    expect(screen.getByTestId('project-drop-hint')).toBeInTheDocument();

    fireEvent.dragLeave(zone, { dataTransfer: { files: [] } });
    expect(screen.queryByTestId('project-drop-hint')).not.toBeInTheDocument();
  });

  /* ── Store session count triggers refresh ─────────────────────── */

  it('store session count change triggers debounced project list refresh', async () => {
    vi.useFakeTimers();
    try {
      listMock.mockResolvedValue([]);
      renderWithI18n(<WorkbenchProjectList onOpenSession={onOpenSession} />);
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
});

/* ═══════════════════════════════════════════════════════════════════
 * M3: Workbench-specific expanded panels (overview + materials)
 * These tests verify the panels that ONLY appear in WorkbenchProjectList,
 * not in SidebarProjectList (Scheme 3 split).
 * ═══════════════════════════════════════════════════════════════════ */

describe('WorkbenchProjectList — M3 expanded panels', () => {
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
      updateMaterialMock,
    ].forEach((m) => m.mockReset());
    listMaterialsMock.mockResolvedValue([]);
    onOpenSession.mockReset();
    useStore.setState({ currentSessionId: null, sessions: [] });
  });

  it('expanded project shows overview panel with description and instructions', async () => {
    listMock.mockResolvedValue(projects);
    listSessionsMock.mockResolvedValue([]);
    renderWithI18n(<WorkbenchProjectList onOpenSession={onOpenSession} />);

    await waitFor(() => screen.getAllByTestId('project-row'));
    // Panels only render when expanded
    expect(screen.queryByTestId('project-overview-panel')).not.toBeInTheDocument();
    expect(screen.queryByTestId('project-materials-panel')).not.toBeInTheDocument();

    // Expand first project
    fireEvent.click(screen.getAllByTestId('project-expand')[0]);
    await waitFor(() => {
      expect(screen.getByTestId('project-overview-panel')).toBeInTheDocument();
      expect(screen.getByTestId('project-materials-panel')).toBeInTheDocument();
    });
    // Overview textareas pre-filled from project data
    expect(screen.getByTestId('project-overview-description')).toHaveValue('desc-p1');
    expect(screen.getByTestId('project-overview-instructions')).toHaveValue('instr-p1');
  });

  it('overview save button is disabled until draft is dirty', async () => {
    listMock.mockResolvedValue(projects);
    listSessionsMock.mockResolvedValue([]);
    renderWithI18n(<WorkbenchProjectList onOpenSession={onOpenSession} />);

    await waitFor(() => screen.getAllByTestId('project-row'));
    fireEvent.click(screen.getAllByTestId('project-expand')[0]);

    await waitFor(() => {
      expect(screen.getByTestId('project-overview-save')).toBeInTheDocument();
    });
    // Initially not dirty → disabled
    expect(screen.getByTestId('project-overview-save')).toBeDisabled();

    // Type in description → dirty → enabled
    fireEvent.change(screen.getByTestId('project-overview-description'), {
      target: { value: 'updated description' },
    });
    expect(screen.getByTestId('project-overview-save')).toBeEnabled();
  });

  it('materials panel shows empty state when no materials', async () => {
    listMock.mockResolvedValue(projects);
    listSessionsMock.mockResolvedValue([]);
    listMaterialsMock.mockResolvedValue([]);
    renderWithI18n(<WorkbenchProjectList onOpenSession={onOpenSession} />);

    await waitFor(() => screen.getAllByTestId('project-row'));
    fireEvent.click(screen.getAllByTestId('project-expand')[0]);

    await waitFor(() => {
      expect(screen.getByTestId('project-materials-panel')).toBeInTheDocument();
    });
    expect(screen.getByTestId('project-materials-empty')).toBeInTheDocument();
  });

  it('materials panel renders material list when materials exist', async () => {
    listMock.mockResolvedValue(projects);
    listSessionsMock.mockResolvedValue([]);
    listMaterialsMock.mockResolvedValue(materialsFixture);
    renderWithI18n(<WorkbenchProjectList onOpenSession={onOpenSession} />);

    await waitFor(() => screen.getAllByTestId('project-row'));
    fireEvent.click(screen.getAllByTestId('project-expand')[0]);

    await waitFor(() => {
      expect(screen.getByTestId('project-material-list')).toBeInTheDocument();
    });
    expect(screen.getAllByTestId('project-material-row')).toHaveLength(1);
    // Material name is not shown as text; instead a "直接录入" label + toggle are rendered
    expect(screen.getByTestId('project-material-toggle')).toBeInTheDocument();
  });

  it('save answer as material button is visible when currentSessionId is set', async () => {
    listMock.mockResolvedValue(projects);
    listSessionsMock.mockResolvedValue([]);
    listMaterialsMock.mockResolvedValue([]);
    useStore.setState({ currentSessionId: 'active-session' });
    renderWithI18n(<WorkbenchProjectList onOpenSession={onOpenSession} />);

    await waitFor(() => screen.getAllByTestId('project-row'));
    fireEvent.click(screen.getAllByTestId('project-expand')[0]);

    await waitFor(() => {
      expect(screen.getByTestId('project-save-answer')).toBeInTheDocument();
    });
  });

  it('materials watermark bar shown when materials exist', async () => {
    listMock.mockResolvedValue(projects);
    listSessionsMock.mockResolvedValue([]);
    listMaterialsMock.mockResolvedValue(materialsFixture);
    useStore.setState({ currentSessionId: null });
    renderWithI18n(<WorkbenchProjectList onOpenSession={onOpenSession} />);

    await waitFor(() => screen.getAllByTestId('project-row'));
    fireEvent.click(screen.getAllByTestId('project-expand')[0]);

    await waitFor(() => {
      // watermark bar appears when list.length > 0 (shows enabled/total count)
      expect(screen.getByTestId('project-materials-watermark')).toBeInTheDocument();
    });
  });

  it('save-answer button disabled when no currentSessionId', async () => {
    listMock.mockResolvedValue(projects);
    listSessionsMock.mockResolvedValue([]);
    listMaterialsMock.mockResolvedValue([]);
    useStore.setState({ currentSessionId: null });
    renderWithI18n(<WorkbenchProjectList onOpenSession={onOpenSession} />);

    await waitFor(() => screen.getAllByTestId('project-row'));
    fireEvent.click(screen.getAllByTestId('project-expand')[0]);

    await waitFor(() => {
      expect(screen.getByTestId('project-save-answer')).toBeDisabled();
    });
  });
});
