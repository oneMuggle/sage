// @vitest-environment jsdom
/**
 * browserSettingsClient 必须走 Electron 主进程鉴权中继（sage:backend-request）。
 *
 * 回归背景：渲染层裸 fetch 到 /api/v1/diagnostic/browser/* 不带本地 bearer
 * token，被 LocalAuthMiddleware 401，设置页误显示「未发现可用浏览器」。
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import { fetchBrowserList, setBrowserPath } from '../browserSettingsClient';

function stubElectron(bridge: ReturnType<typeof vi.fn>): void {
  (window as unknown as { electronAPI?: unknown }).electronAPI = { backendRequest: bridge };
}

afterEach(() => {
  delete (window as unknown as { electronAPI?: unknown }).electronAPI;
  vi.unstubAllGlobals();
});

describe('browserSettingsClient', () => {
  it('routes list requests through the Electron main relay (auth injection)', async () => {
    const bridge = vi.fn(async () => ({
      browsers: [],
      userConfigured: null,
      embeddedAvailable: true,
    }));
    stubElectron(bridge);
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    await fetchBrowserList();

    expect(bridge).toHaveBeenCalledWith({
      method: 'GET',
      path: '/api/v1/diagnostic/browser/list',
      body: undefined,
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('sends browser selection as a JSON body through the relay', async () => {
    const bridge = vi.fn(async () => ({ success: true }));
    stubElectron(bridge);

    await setBrowserPath('(embedded)');

    expect(bridge).toHaveBeenCalledWith({
      method: 'PUT',
      path: '/api/v1/diagnostic/browser/path',
      body: { path: '(embedded)' },
    });
  });

  it('propagates relay failures so the UI can render an error state', async () => {
    const bridge = vi.fn(async () => {
      throw new Error('Backend request failed: 401');
    });
    stubElectron(bridge);

    await expect(fetchBrowserList()).rejects.toThrow('401');
  });
});
