/**
 * 启动竞态回归：`backend:starting` 事件通常在 renderer 订阅之前发出，
 * 组件挂载时必须用 `getBackendLifecycle()` 快照补显「后端服务正在启动…」。
 */
import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { BackendStatusBanner } from '../BackendStatusBanner';

const listenMock = vi.fn();
const getLifecycleMock = vi.fn();

describe('BackendStatusBanner lifecycle snapshot fallback', () => {
  beforeEach(() => {
    listenMock.mockReset();
    listenMock.mockResolvedValue(() => undefined);
    getLifecycleMock.mockReset();
    (window as unknown as { electronAPI?: unknown }).electronAPI = {
      listen: listenMock,
      getBackendLifecycle: getLifecycleMock,
    };
  });

  afterEach(() => {
    delete (window as { electronAPI?: unknown }).electronAPI;
  });

  it('事件丢失时用 starting 快照补显横幅', async () => {
    getLifecycleMock.mockResolvedValue({ lifecycle: 'starting', generation: 1 });
    render(<BackendStatusBanner />);
    await waitFor(() => expect(screen.getByTestId('backend-banner-starting')).toBeInTheDocument());
  });

  it('快照为 ready 时不显示横幅', async () => {
    getLifecycleMock.mockResolvedValue({ lifecycle: 'ready', generation: 1 });
    render(<BackendStatusBanner />);
    await waitFor(() => expect(getLifecycleMock).toHaveBeenCalled());
    expect(screen.queryByTestId('backend-banner-starting')).not.toBeInTheDocument();
  });
});
