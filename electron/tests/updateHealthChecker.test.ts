// @vitest-environment node
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('electron', () => ({
  BrowserWindow: vi.fn(),
}));

const { LauncherHealthChecker } = await import('../updateHealthChecker');

interface MockWindow {
  isDestroyed: ReturnType<typeof vi.fn>;
  isVisible: ReturnType<typeof vi.fn>;
  webContents: { executeJavaScript: ReturnType<typeof vi.fn> };
}

function createMockWindow(overrides: { visible?: boolean; destroyed?: boolean } = {}): MockWindow {
  return {
    webContents: { executeJavaScript: vi.fn().mockResolvedValue(true) },
    isDestroyed: vi.fn().mockReturnValue(overrides.destroyed ?? false),
    isVisible: vi.fn().mockReturnValue(overrides.visible ?? true),
  };
}

function createOkResponse(): Response {
  return { ok: true, status: 200, json: async () => [] } as unknown as Response;
}

describe('LauncherHealthChecker', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('returns passed:true when all 4 checks succeed', async () => {
    const mockWin = createMockWindow({ visible: true });
    vi.mocked(fetch).mockResolvedValue(createOkResponse());

    const checker = new LauncherHealthChecker({
      getWindow: () => mockWin as unknown as Electron.BrowserWindow,
    });

    const promise = checker.runPostStartupChecks();
    await vi.runAllTimersAsync();
    const result = await promise;

    expect(result.passed).toBe(true);
    expect(result.details).toHaveLength(4);
    expect(result.details.map((d) => d.name)).toEqual(['mainWindow', 'backend', 'database', 'ipc']);
    expect(result.details.every((d) => d.passed)).toBe(true);
  });

  it('returns passed:false with error details when backend check fails', async () => {
    const mockWin = createMockWindow({ visible: true });
    vi.mocked(fetch).mockRejectedValue(new Error('connection refused'));

    const checker = new LauncherHealthChecker({
      getWindow: () => mockWin as unknown as Electron.BrowserWindow,
    });

    const promise = checker.runPostStartupChecks();
    await vi.runAllTimersAsync();
    const result = await promise;

    expect(result.passed).toBe(false);
    const backendDetail = result.details.find((d) => d.name === 'backend');
    expect(backendDetail).toBeDefined();
    expect(backendDetail?.passed).toBe(false);
    expect(backendDetail?.error).toContain('Python backend failed to become healthy');
  });

  it('retries backend health check 10 times before failing', async () => {
    const mockWin = createMockWindow({ visible: true });
    vi.mocked(fetch).mockRejectedValue(new Error('connection refused'));

    const checker = new LauncherHealthChecker({
      getWindow: () => mockWin as unknown as Electron.BrowserWindow,
    });

    const promise = checker.runPostStartupChecks();
    await vi.runAllTimersAsync();
    await promise;

    // Ten backend probes plus one independent authenticated database probe.
    expect(
      vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith('/health')),
    ).toHaveLength(10);
  });

  it('times out main window check after 3 seconds', async () => {
    // Window never becomes visible
    const checker = new LauncherHealthChecker({
      getWindow: () => null,
    });

    const promise = checker.runPostStartupChecks();
    // Also make backend fail fast so it does not block
    vi.mocked(fetch).mockResolvedValue(createOkResponse());

    await vi.runAllTimersAsync();
    const result = await promise;

    const mainWindowDetail = result.details.find((d) => d.name === 'mainWindow');
    expect(mainWindowDetail?.passed).toBe(false);
    expect(mainWindowDetail?.error).toContain('Main window not visible within 3 seconds');
  });

  it('accepts custom backend URL via constructor', async () => {
    const mockWin = createMockWindow({ visible: true });
    vi.mocked(fetch).mockResolvedValue(createOkResponse());

    const checker = new LauncherHealthChecker({
      getWindow: () => mockWin as unknown as Electron.BrowserWindow,
      backendUrl: 'http://custom-host:9999',
    });

    const promise = checker.runPostStartupChecks();
    await vi.runAllTimersAsync();
    await promise;

    expect(fetch).toHaveBeenCalledWith(
      'http://custom-host:9999/health',
      expect.objectContaining({ signal: expect.any(Object) }),
    );
  });

  it('main window check passes when window becomes visible after initial polls', async () => {
    let pollCount = 0;
    const mockWin = createMockWindow({ visible: false });
    mockWin.isVisible.mockImplementation(() => {
      pollCount += 1;
      return pollCount >= 5;
    });
    vi.mocked(fetch).mockResolvedValue(createOkResponse());

    const checker = new LauncherHealthChecker({
      getWindow: () => mockWin as unknown as Electron.BrowserWindow,
    });

    const promise = checker.runPostStartupChecks();
    await vi.runAllTimersAsync();
    const result = await promise;

    const mainWindowDetail = result.details.find((d) => d.name === 'mainWindow');
    expect(mainWindowDetail?.passed).toBe(true);
  });

  it('probes the database with auth and invokes the real renderer IPC bridge', async () => {
    const mockWin = createMockWindow({ visible: true });
    vi.mocked(fetch).mockResolvedValue(createOkResponse());

    const checker = new LauncherHealthChecker({
      getWindow: () => mockWin as unknown as Electron.BrowserWindow,
    });

    const promise = checker.runPostStartupChecks();
    await vi.runAllTimersAsync();
    const result = await promise;

    expect(mockWin.webContents.executeJavaScript).toHaveBeenCalledWith(
      expect.stringContaining("api.invoke('list_sessions'"),
    );
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/sessions?limit=1'),
      expect.any(Object),
    );
    const dbDetail = result.details.find((d) => d.name === 'database');
    const ipcDetail = result.details.find((d) => d.name === 'ipc');
    expect(dbDetail?.passed).toBe(true);
    expect(ipcDetail?.passed).toBe(true);
    expect(dbDetail?.error).toBeUndefined();
    expect(ipcDetail?.error).toBeUndefined();
  });
  it('reports database failure and hung IPC independently, clearing all timers', async () => {
    const mockWin = createMockWindow();
    mockWin.webContents.executeJavaScript.mockReturnValue(new Promise(() => {}));
    vi.mocked(fetch).mockImplementation(async (url) =>
      String(url).includes('/sessions')
        ? ({ ok: false, status: 500 } as Response)
        : createOkResponse(),
    );
    const checker = new LauncherHealthChecker({
      getWindow: () => mockWin as unknown as Electron.BrowserWindow,
      getAuthToken: () => 'test-capability',
      ipcTimeout: 50,
    });
    const pending = checker.runPostStartupChecks();
    await vi.runAllTimersAsync();
    const result = await pending;
    expect(result.details.find((d) => d.name === 'database')?.passed).toBe(false);
    expect(result.details.find((d) => d.name === 'ipc')?.error).toContain('timed out');
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/sessions'),
      expect.objectContaining({
        headers: { 'X-Sage-Local-Authorization': 'Bearer test-capability' },
      }),
    );
    expect(vi.getTimerCount()).toBe(0);
  });

  it('fails a malformed database response and a rejected renderer bridge', async () => {
    const mockWin = createMockWindow();
    mockWin.webContents.executeJavaScript.mockRejectedValue(new Error('bridge unavailable'));
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({}),
    } as Response);
    const checker = new LauncherHealthChecker({
      getWindow: () => mockWin as unknown as Electron.BrowserWindow,
    });
    const pending = checker.runPostStartupChecks();
    await vi.runAllTimersAsync();
    const result = await pending;
    expect(result.passed).toBe(false);
    expect(result.details.find((d) => d.name === 'database')?.error).toContain('Invalid database');
    expect(result.details.find((d) => d.name === 'ipc')?.error).toContain('bridge unavailable');
    expect(vi.getTimerCount()).toBe(0);
  });
});
