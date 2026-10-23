import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { ProjectBadge } from '../ProjectBadge';

const listMock = vi.fn();

vi.mock('../../../shared/api/projectApi', () => ({
  projectApi: {
    list: (...args: unknown[]) => listMock(...args),
  },
}));

describe('ProjectBadge', () => {
  beforeEach(() => {
    listMock.mockReset();
  });

  it('无工作区绑定时完全不渲染', () => {
    const { container } = render(<ProjectBadge workspacePath={null} />);
    expect(container).toBeEmptyDOMElement();
    expect(listMock).not.toHaveBeenCalled();
  });

  it('已登记项目显示注册名，tooltip 为完整路径', async () => {
    listMock.mockResolvedValue([
      {
        id: 'p1',
        path: 'C:\\work\\demo',
        name: 'demo',
        createdAt: 1,
        lastOpenedAt: 1,
        sessionCount: 1,
        lastSessionId: 's1',
      },
    ]);
    render(<ProjectBadge workspacePath={'C:\\work\\demo'} />);

    await waitFor(() => {
      expect(screen.getByTestId('chat-project-badge')).toBeInTheDocument();
      expect(screen.getByText('demo')).toBeInTheDocument();
    });
    expect(screen.getByTestId('chat-project-badge').getAttribute('title')).toBe('C:\\work\\demo');
  });

  it('已登记项目存在形态、阶段与版本保护时展示多态徽标并支持复制路径与打开工作台 (Phase P22 + P28)', async () => {
    const onOpenWorkbench = vi.fn();
    listMock.mockResolvedValue([
      {
        id: 'p2',
        path: 'D:\\Archives\\Contract2026',
        name: 'Contract2026',
        projectType: 'business',
        projectStage: 'execution',
        vcsMode: 'builtin',
        createdAt: 1,
        lastOpenedAt: 1,
        sessionCount: 2,
        lastSessionId: 's2',
      },
    ]);
    render(
      <ProjectBadge
        workspacePath={'D:\\Archives\\Contract2026'}
        onOpenWorkbench={onOpenWorkbench}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId('chat-project-type-badge')).toHaveTextContent('一般档案与文书');
      expect(screen.getByTestId('chat-project-stage-badge')).toHaveTextContent('文书编制');
      expect(screen.getByTestId('chat-project-vcs-badge')).toHaveTextContent('快照');
    });

    const copyBtn = screen.getByTestId('chat-project-copy-path-btn');
    fireEvent.click(copyBtn);

    const workbenchBtn = screen.getByTestId('chat-project-workbench-btn');
    fireEvent.click(workbenchBtn);
    expect(onOpenWorkbench).toHaveBeenCalledTimes(1);
  });

  it('路径未登记（历史绑定）回退为 basename 展示', async () => {
    listMock.mockResolvedValue([]);
    render(<ProjectBadge workspacePath={'C:\\work\\not-registered'} />);

    await waitFor(() => {
      expect(screen.getByText('not-registered')).toBeInTheDocument();
    });
  });

  it('清单拉取失败静默降级为 basename 展示', async () => {
    listMock.mockRejectedValue(new Error('backend offline'));
    render(<ProjectBadge workspacePath={'C:\\work\\fallback-name'} />);

    await waitFor(() => {
      expect(screen.getByText('fallback-name')).toBeInTheDocument();
    });
  });
});
