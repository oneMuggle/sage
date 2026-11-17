/**
 * StartupStatusIndicator：warming 进度 / L3 自动隐藏 / 降级常驻提示。
 */
import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { StartupStatusSnapshot } from '../../../shared/types/electron-api';
import { StartupStatusIndicator } from '../StartupStatusIndicator';

function installApi(snapshot: StartupStatusSnapshot | null) {
  const getter = vi.fn().mockResolvedValue(snapshot);
  (window as unknown as { electronAPI?: unknown }).electronAPI = {
    listen: vi.fn().mockResolvedValue(() => undefined),
    getBackendStartupStatus: getter,
  };
  return getter;
}

const warming: StartupStatusSnapshot = {
  status: 'warming',
  phase: 'L2',
  boot_ms: 4100,
  modules: {
    database: { state: 'ready', layer: 1, elapsed_ms: 812, detail: null },
    mcp: { state: 'warming', layer: 3, elapsed_ms: null, detail: null },
  },
  warmup: { done: 8, total: 15 },
};

const ready: StartupStatusSnapshot = {
  status: 'ready',
  phase: 'L3',
  boot_ms: 6000,
  modules: {
    database: { state: 'ready', layer: 1, elapsed_ms: 812, detail: null },
    mcp: { state: 'ready', layer: 3, elapsed_ms: 2500, detail: null },
  },
  warmup: { done: 2, total: 2 },
};

const degraded: StartupStatusSnapshot = {
  status: 'degraded',
  phase: 'L3',
  boot_ms: 9000,
  modules: {
    database: { state: 'ready', layer: 1, elapsed_ms: 812, detail: null },
    mcp: { state: 'degraded', layer: 3, elapsed_ms: 9000, detail: { servers: [] } },
  },
  warmup: { done: 2, total: 2 },
};

describe('StartupStatusIndicator', () => {
  afterEach(() => {
    delete (window as { electronAPI?: unknown }).electronAPI;
  });

  it('shows warmup progress before L3', async () => {
    installApi(warming);
    render(<StartupStatusIndicator />);
    await waitFor(() =>
      expect(screen.getByTestId('startup-status-indicator')).toHaveAttribute(
        'data-state',
        'warming',
      ),
    );
    expect(screen.getByText(/正在加载后台服务（8\/15）/)).toBeInTheDocument();
  });

  it('stays hidden once L3 has no degraded modules', async () => {
    const getter = installApi(ready);
    render(<StartupStatusIndicator />);
    await waitFor(() => expect(getter).toHaveBeenCalled());
    expect(screen.queryByTestId('startup-status-indicator')).not.toBeInTheDocument();
  });

  it('shows degraded summary at L3', async () => {
    installApi(degraded);
    render(<StartupStatusIndicator />);
    await waitFor(() =>
      expect(screen.getByTestId('startup-status-indicator')).toHaveAttribute(
        'data-state',
        'degraded',
      ),
    );
    expect(screen.getByText(/1 项功能降级：MCP 服务/)).toBeInTheDocument();
  });
});
