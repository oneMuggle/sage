import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useChangesListStore } from '../../../../features/changes/changesListStore';
import { useRightPanelStore } from '../../../../features/right-panel/rightPanelStore';
import type { WorkspaceChanges } from '../../../../shared/api/workspaceApi';
import { I18nProvider } from '../../../../shared/lib/i18n';
import { FileChangeCard } from '../FileChangeCard';

const mocks = vi.hoisted(() => ({
  getChangeDiff: vi.fn(() => Promise.resolve({ diff: '', truncated: false })),
  getChanges: vi.fn(),
  confirmDialog: vi.fn(),
  copyToClipboard: vi.fn(() => Promise.resolve(true)),
}));

vi.mock('../../../../shared/api/workspaceApi', () => ({
  workspaceApi: {
    getChangeDiff: mocks.getChangeDiff,
    getChanges: mocks.getChanges,
    revertChanges: vi.fn(),
  },
}));

vi.mock('../../../../shared/ui/ConfirmDialog/confirmService', () => ({
  confirmDialog: mocks.confirmDialog,
}));

vi.mock('../../../../shared/lib/clipboard', () => ({
  copyToClipboard: mocks.copyToClipboard,
}));

vi.mock('../../ShikiCodeBlock', () => ({
  ShikiCodeBlock: ({ children }: { children: string }) => <pre>{children}</pre>,
}));

const changes: WorkspaceChanges = {
  branch: 'main',
  upstream: '',
  ahead: 0,
  behind: 0,
  clean: false,
  changes: [
    { indexStatus: '', worktreeStatus: 'M', path: 'src/app.ts', insertions: 1, deletions: 1 },
  ],
};

function renderCard() {
  return render(
    <I18nProvider defaultLocale="zh">
      <FileChangeCard sessionId="s1" path="src/app.ts" />
    </I18nProvider>,
  );
}

function openMenu() {
  fireEvent.contextMenu(screen.getByTestId('file-change-card'), { clientX: 6, clientY: 6 });
}

beforeEach(() => {
  vi.clearAllMocks();
  useChangesListStore.setState({ bySession: { s1: changes }, errors: {}, loadingBy: {} });
  useRightPanelStore.setState({ open: false, selectedChangePath: null });
});

describe('FileChangeCard — context menu', () => {
  it('exposes accept/revert/view actions', async () => {
    renderCard();
    openMenu();

    expect(await screen.findByRole('menuitem', { name: '接受此变更' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: '回滚此变更…' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: '切换 diff 视图' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: '在编辑器中打开' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: '在右侧面板查看' })).toBeInTheDocument();
  });

  it('opens the change in the right panel and copies the path', async () => {
    renderCard();
    openMenu();

    fireEvent.click(await screen.findByRole('menuitem', { name: '在右侧面板查看' }));
    expect(useRightPanelStore.getState().selectedChangePath).toBe('src/app.ts');

    openMenu();
    fireEvent.click(await screen.findByRole('menuitem', { name: '复制路径' }));
    expect(mocks.copyToClipboard).toHaveBeenCalledWith('src/app.ts', expect.any(Object));
  });

  it('routes revert through the confirmation dialog', async () => {
    mocks.confirmDialog.mockResolvedValueOnce(false);
    renderCard();
    openMenu();

    fireEvent.click(await screen.findByRole('menuitem', { name: '回滚此变更…' }));

    await waitFor(() => expect(mocks.confirmDialog).toHaveBeenCalledTimes(1));
  });
});
