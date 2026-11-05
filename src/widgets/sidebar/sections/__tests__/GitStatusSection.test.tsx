import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { GitStatusResponse } from '../../../../shared/api/gitStatusApi';
import { getGitStatus } from '../../../../shared/api/gitStatusApi';
import { projectApi } from '../../../../shared/api/projectApi';
import { useCurrentWorkspace } from '../../../../shared/lib/workspaceContext';
import { GitStatusSection } from '../GitStatusSection';

// Mock dependencies
vi.mock('../../../../shared/api/gitStatusApi');
vi.mock('../../../../shared/api/projectApi');
vi.mock('../../../../shared/lib/workspaceContext');
vi.mock('../../../../shared/lib/i18n', () => ({
  useI18n: () => ({
    t: (key: string) => key,
    language: 'zh',
  }),
  TranslationKey: String,
}));
vi.mock('../../../../shared/lib/clipboard', () => ({
  copyToClipboard: vi.fn(),
}));
vi.mock('../../SiderSection', () => ({
  SiderSection: ({ render, label }: { render: () => React.ReactNode; label: string }) => (
    <div data-testid="sider-section" data-label={label}>
      {render()}
    </div>
  ),
}));
vi.mock('../GitDiffDrawer', () => ({
  GitDiffDrawer: () => null,
}));
vi.mock('../gitFileContextMenu', () => ({
  buildGitFileContextMenuItems: () => [],
}));
vi.mock('../../../../shared/ui/ContextMenu/ContextMenu', () => ({
  ContextMenu: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

const mockGetGitStatus = vi.mocked(getGitStatus);
const mockProjectApiList = vi.mocked(projectApi.list);
const mockUseCurrentWorkspace = vi.mocked(useCurrentWorkspace);

const mockGitStatusResponse = (isGitRepo: boolean): GitStatusResponse => ({
  is_git_repo: isGitRepo,
  branch: 'main',
  ahead: 0,
  behind: 0,
  files: [],
});

describe('GitStatusSection — 数据源优先级', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetGitStatus.mockResolvedValue(mockGitStatusResponse(true));
  });

  it('优先使用当前会话 workspace 路径', async () => {
    mockUseCurrentWorkspace.mockReturnValue('/workspace/current-session');
    mockProjectApiList.mockResolvedValue([
      {
        id: 'p1',
        path: '/workspace/recent-project',
        name: 'Recent',
        lastOpenedAt: Date.now(),
      } as never,
    ]);

    render(<GitStatusSection collapsed={false} onToggleCollapsed={vi.fn()} />);

    await waitFor(() => {
      expect(mockGetGitStatus).toHaveBeenCalledWith('/workspace/current-session');
    });
    expect(mockGetGitStatus).not.toHaveBeenCalledWith('/workspace/recent-project');
  });

  it('workspace 为空时，回退到最近打开的项目', async () => {
    mockUseCurrentWorkspace.mockReturnValue(undefined);
    mockProjectApiList.mockResolvedValue([
      {
        id: 'p1',
        path: '/workspace/recent-project',
        name: 'Recent',
        lastOpenedAt: Date.now(),
      } as never,
    ]);

    render(<GitStatusSection collapsed={false} onToggleCollapsed={vi.fn()} />);

    await waitFor(() => {
      expect(mockGetGitStatus).toHaveBeenCalledWith('/workspace/recent-project');
    });
  });

  it('workspace 和项目都为空时，不调用 getGitStatus', async () => {
    mockUseCurrentWorkspace.mockReturnValue(undefined);
    mockProjectApiList.mockResolvedValue([]);

    render(<GitStatusSection collapsed={false} onToggleCollapsed={vi.fn()} />);

    // 等待异步操作完成
    await new Promise((r) => setTimeout(r, 50));
    expect(mockGetGitStatus).not.toHaveBeenCalled();
  });

  it('非 git 仓库时显示目录路径', async () => {
    mockUseCurrentWorkspace.mockReturnValue('/workspace/not-a-repo');
    mockGetGitStatus.mockResolvedValue(mockGitStatusResponse(false));

    render(<GitStatusSection collapsed={false} onToggleCollapsed={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText('git.not_a_repo')).toBeInTheDocument();
    });
    expect(screen.getByText('/workspace/not-a-repo')).toBeInTheDocument();
  });
});
