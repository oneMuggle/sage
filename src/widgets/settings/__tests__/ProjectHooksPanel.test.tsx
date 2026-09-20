import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// Mock backendRequest
vi.mock('../../../shared/api/backendRequest', () => ({
  backendRequest: vi.fn(),
}));

// Mock useCurrentWorkspace
vi.mock('../../../shared/lib/workspaceContext', () => ({
  useCurrentWorkspace: vi.fn(),
}));

// Mock toast
vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

import { backendRequest } from '../../../shared/api/backendRequest';
import { useCurrentWorkspace } from '../../../shared/lib/workspaceContext';
import { ProjectHooksPanel } from '../ProjectHooksPanel';

describe('ProjectHooksPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('不渲染当没有 workspace 时', () => {
    vi.mocked(useCurrentWorkspace).mockReturnValue(undefined);
    const { container } = render(<ProjectHooksPanel />);
    expect(container.firstChild).toBeNull();
  });

  it('不渲染当没有配置文件时', async () => {
    vi.mocked(useCurrentWorkspace).mockReturnValue('/test/workspace');
    vi.mocked(backendRequest).mockResolvedValue({
      workspace: '/test/workspace',
      trusted: false,
      config_exists: false,
      hook_count: 0,
    });

    render(<ProjectHooksPanel />);
    await vi.waitFor(() => {
      expect(backendRequest).toHaveBeenCalled();
    });

    expect(screen.queryByText(/项目级 Hook/)).toBeNull();
  });

  it('显示信任提示当存在未信任的配置时', async () => {
    vi.mocked(useCurrentWorkspace).mockReturnValue('/test/workspace');
    vi.mocked(backendRequest).mockResolvedValue({
      workspace: '/test/workspace',
      trusted: false,
      config_exists: true,
      hook_count: 2,
    });

    render(<ProjectHooksPanel />);
    await vi.waitFor(() => {
      expect(screen.getByText(/检测到项目级 Hook 配置/)).toBeInTheDocument();
    });

    expect(screen.getByText(/信任并启用/)).toBeInTheDocument();
    expect(screen.getByText('/test/workspace')).toBeInTheDocument();
  });

  it('显示已启用状态当已信任时', async () => {
    vi.mocked(useCurrentWorkspace).mockReturnValue('/test/workspace');
    vi.mocked(backendRequest).mockResolvedValue({
      workspace: '/test/workspace',
      trusted: true,
      config_exists: true,
      hook_count: 3,
    });

    render(<ProjectHooksPanel />);
    await vi.waitFor(() => {
      expect(screen.getByText(/项目级 Hook 已启用/)).toBeInTheDocument();
    });

    expect(screen.queryByText(/信任并启用/)).toBeNull();
  });
});
