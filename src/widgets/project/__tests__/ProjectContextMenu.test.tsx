// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ProjectSummary } from '../../../shared/api/projectApi';
import { ProjectContextMenu } from '../ProjectContextMenu';

const project: ProjectSummary = {
  id: 'p1',
  path: '/work/demo',
  name: 'demo',
  createdAt: 1,
  lastOpenedAt: 1,
  allowedPaths: [],
  sessionCount: 1,
  lastSessionId: 's1',
};

const renderMenu = (overrides: Partial<Parameters<typeof ProjectContextMenu>[0]> = {}) =>
  render(
    <ProjectContextMenu
      project={project}
      onOpen={vi.fn()}
      onNewSession={vi.fn()}
      onSettings={vi.fn()}
      onCheckPlaybook={vi.fn()}
      onRemove={vi.fn()}
      {...overrides}
    >
      <button type="button">项目行</button>
    </ProjectContextMenu>,
  );

describe('ProjectContextMenu', () => {
  const openFolder = vi.fn();
  const revealFolder = vi.fn();

  beforeEach(() => {
    openFolder.mockReset();
    revealFolder.mockReset();
    (window as unknown as { electronAPI: unknown }).electronAPI = {
      project: { openFolder, revealFolder },
    };
  });

  it('opens the project folder through the validated IPC bridge', async () => {
    openFolder.mockResolvedValue({ success: true });
    renderMenu();

    fireEvent.contextMenu(screen.getByText('项目行'));
    fireEvent.click(await screen.findByText('打开项目文件夹'));

    await waitFor(() => expect(openFolder).toHaveBeenCalledWith('p1'));
  });

  it('reveals the project folder', async () => {
    revealFolder.mockResolvedValue({ success: true });
    renderMenu();

    fireEvent.contextMenu(screen.getByText('项目行'));
    fireEvent.click(await screen.findByText('在文件管理器中显示'));

    await waitFor(() => expect(revealFolder).toHaveBeenCalledWith('p1'));
  });

  it('invokes the provided row actions', async () => {
    const onOpen = vi.fn();
    const onNewSession = vi.fn();
    const onSettings = vi.fn();
    const onCheckPlaybook = vi.fn();
    const onRemove = vi.fn();
    renderMenu({ onOpen, onNewSession, onSettings, onCheckPlaybook, onRemove });

    fireEvent.contextMenu(screen.getByText('项目行'));
    fireEvent.click(await screen.findByText('打开项目'));
    fireEvent.contextMenu(screen.getByText('项目行'));
    fireEvent.click(await screen.findByText('新建会话'));
    fireEvent.contextMenu(screen.getByText('项目行'));
    fireEvent.click(await screen.findByText('项目设置与 AI 初始化…'));
    fireEvent.contextMenu(screen.getByText('项目行'));
    fireEvent.click(await screen.findByText('检查项目完整性'));
    fireEvent.contextMenu(screen.getByText('项目行'));
    fireEvent.click(await screen.findByText('移除项目'));

    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onNewSession).toHaveBeenCalledTimes(1);
    expect(onSettings).toHaveBeenCalledTimes(1);
    expect(onCheckPlaybook).toHaveBeenCalledTimes(1);
    expect(onRemove).toHaveBeenCalledTimes(1);
  });
});
