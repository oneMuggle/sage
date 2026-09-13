import { render, screen, waitFor } from '@testing-library/react';
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
