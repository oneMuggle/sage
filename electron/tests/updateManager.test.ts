// @vitest-environment node
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import * as fs from 'fs/promises';

const mockUserData = '/tmp/test-user-data-update-manager';

vi.mock('electron', () => ({
  app: {
    getPath: (name: string) => {
      if (name === 'userData') return mockUserData;
      throw new Error(`Unknown path: ${name}`);
    },
    getVersion: () => '1.0.0',
    relaunch: vi.fn(),
    exit: vi.fn(),
  },
  BrowserWindow: vi.fn(),
}));

vi.mock('electron-updater', () => ({
  autoUpdater: {},
}));

// Mock the health checker so onAppStartup tests run instantly instead of
// waiting through 10 retry cycles (10+ seconds of real timers).
let mockRunPostStartupChecks: ReturnType<typeof vi.fn>;
vi.doMock('../updateHealthChecker', () => ({
  LauncherHealthChecker: vi.fn().mockImplementation(() => ({
    runPostStartupChecks: mockRunPostStartupChecks,
  })),
}));

const { UpdateManager } = await import('../updateManager');
const { StateManager } = await import('../updateState');

const platformKey =
  process.platform === 'linux'
    ? 'linux-x64'
    : process.platform === 'darwin'
      ? process.arch === 'arm64'
        ? 'mac-arm64'
        : 'mac-x64'
      : process.arch === 'x64'
        ? 'win-x64'
        : 'win-ia32';

function createResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

function updaterChannelFile(channel: 'stable' | 'beta' | 'alpha'): string {
  const prefix = channel === 'stable' ? 'latest' : channel;
  if (process.platform === 'linux') return `${prefix}-linux.yml`;
  if (process.platform === 'darwin') return `${prefix}-mac.yml`;
  return `${prefix}.yml`;
}

function createManifest(
  version: string,
  options: {
    channel?: 'stable' | 'beta' | 'alpha';
    minimum?: string;
    includePlatformFile?: boolean;
  } = {},
): Record<string, unknown> {
  const channel = options.channel ?? 'stable';
  return {
    version,
    channel,
    release_date: '2026-09-05T12:00:00Z',
    release_notes: '## New features',
    min_upgradable_version: options.minimum ?? '1.0.0',
    files:
      options.includePlatformFile === false
        ? {}
        : {
            [platformKey]: {
              filename: `Sage-Setup-${version}.bin`,
              url: `https://updates.sage.app/releases/${version}/${updaterChannelFile(channel)}`,
              sha512: 'a'.repeat(128),
              size: 104857600,
              signature: 'sig',
            },
          },
    components: {},
  };
}

interface FakeUpdater {
  setFeedURL: ReturnType<typeof vi.fn>;
  checkForUpdates: ReturnType<typeof vi.fn>;
  downloadUpdate: ReturnType<typeof vi.fn>;
  quitAndInstall: ReturnType<typeof vi.fn>;
  on: ReturnType<typeof vi.fn>;
  off: ReturnType<typeof vi.fn>;
}

function createFakeUpdater(): FakeUpdater {
  return {
    setFeedURL: vi.fn(),
    checkForUpdates: vi.fn().mockResolvedValue({
      updateInfo: {
        version: '1.3.0',
        files: [
          {
            url: 'https://updates.sage.app/releases/1.3.0/Sage-Setup-1.3.0.bin',
            sha512: 'a'.repeat(128),
            size: 104857600,
          },
        ],
      },
    }),
    downloadUpdate: vi.fn().mockResolvedValue([]),
    quitAndInstall: vi.fn(),
    on: vi.fn(),
    off: vi.fn(),
  };
}

describe('UpdateManager', () => {
  let updateManager: InstanceType<typeof UpdateManager>;
  let updater: FakeUpdater;

  beforeEach(async () => {
    await fs.mkdir(mockUserData, { recursive: true });
    await fs.rm(`${mockUserData}/update-state.json`, { force: true });
    await fs.rm(`${mockUserData}/update-config.json`, { force: true });
    // Set manual strategy by default so tests have explicit control
    await fs.writeFile(
      `${mockUserData}/update-config.json`,
      JSON.stringify({
        updateStrategy: 'manual',
        channel: 'stable',
        rollbackWindowDays: 7,
        autoRollbackThreshold: 3,
        checkIntervalHours: 24,
        updateServerUrl: 'https://updates.sage.app',
        enableTelemetry: false,
        cacheRetentionDays: 30,
      }),
    );
    updater = createFakeUpdater();
    updateManager = new UpdateManager(updater);
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(async () => {
    vi.unstubAllGlobals();
    await fs.rm(mockUserData, { recursive: true, force: true });
  });

  it('returns updateAvailable: false when server returns 404', async () => {
    vi.mocked(fetch).mockResolvedValue(createResponse(404, {}));

    const result = await updateManager.checkForUpdates();

    expect(result.updateAvailable).toBe(false);
  });

  it('returns updateAvailable: true when newer version exists', async () => {
    vi.mocked(fetch).mockResolvedValue(createResponse(200, createManifest('1.3.0')));

    const result = await updateManager.checkForUpdates();

    expect(result.updateAvailable).toBe(true);
    expect(result.version).toBe('1.3.0');
    expect(result.releaseNotes).toBe('## New features');
    expect(result.downloadUrl).toBe(
      `https://updates.sage.app/releases/1.3.0/${updaterChannelFile('stable')}`,
    );
  });

  it('returns updateAvailable: false when current version is up to date', async () => {
    vi.mocked(fetch).mockResolvedValue(createResponse(200, createManifest('1.0.0')));

    const result = await updateManager.checkForUpdates();

    expect(result.updateAvailable).toBe(false);
  });

  it('records last check time when server returns 404', async () => {
    vi.mocked(fetch).mockResolvedValue(createResponse(404, {}));

    await updateManager.checkForUpdates();

    const state = JSON.parse(await fs.readFile(`${mockUserData}/update-state.json`, 'utf8'));
    expect(state.lastCheckTime).toEqual(expect.any(String));
  });

  it('rejects an update when current version is below minimum', async () => {
    vi.mocked(fetch).mockResolvedValue(
      createResponse(200, createManifest('1.3.0', { minimum: '1.1.0' })),
    );

    const result = await updateManager.checkForUpdates();

    expect(result.updateAvailable).toBe(false);
  });

  it('compares prerelease versions and large numeric identifiers according to semver ordering', () => {
    const compareVersions = (
      updateManager as unknown as {
        compareVersions: (left: unknown, right: unknown) => number;
      }
    ).compareVersions.bind(updateManager);
    const parseVersion = (
      updateManager as unknown as {
        parseVersion: (version: string, field: string) => unknown;
      }
    ).parseVersion;

    expect(
      compareVersions(parseVersion('1.0.0-beta.2', 'test'), parseVersion('1.0.0-beta.11', 'test')),
    ).toBeLessThan(0);
    expect(
      compareVersions(parseVersion('1.0.0', 'test'), parseVersion('1.0.0-rc.1', 'test')),
    ).toBeGreaterThan(0);
    expect(
      compareVersions(
        parseVersion('9007199254740993.0.0', 'test'),
        parseVersion('9007199254740992.0.0', 'test'),
      ),
    ).toBeGreaterThan(0);
    expect(
      compareVersions(
        parseVersion('1.0.0-9007199254740993', 'test'),
        parseVersion('1.0.0-9007199254740992', 'test'),
      ),
    ).toBeGreaterThan(0);
  });

  it('throws a diagnostic error for an invalid manifest', async () => {
    vi.mocked(fetch).mockResolvedValue(createResponse(200, { version: 'not-a-version' }));

    await expect(updateManager.checkForUpdates()).rejects.toThrow('min_upgradable_version');
  });

  it('throws when the platform file is missing', async () => {
    vi.mocked(fetch).mockResolvedValue(
      createResponse(200, createManifest('1.3.0', { includePlatformFile: false })),
    );

    await expect(updateManager.checkForUpdates()).rejects.toThrow(`files.${platformKey}`);
  });

  it('rejects invalid download URLs', async () => {
    const manifest = createManifest('1.3.0');
    (manifest.files as Record<string, Record<string, string>>)[platformKey].url = 'not-a-url';
    vi.mocked(fetch).mockResolvedValue(createResponse(200, manifest));

    await expect(updateManager.checkForUpdates()).rejects.toThrow(`files.${platformKey}.url`);
  });

  it('rejects incomplete file metadata', async () => {
    const manifest = createManifest('1.3.0');
    delete (manifest.files as Record<string, Record<string, unknown>>)[platformKey].sha512;
    vi.mocked(fetch).mockResolvedValue(createResponse(200, manifest));

    await expect(updateManager.checkForUpdates()).rejects.toThrow(`files.${platformKey}.sha512`);
  });

  it('rejects unsupported platform and architecture combinations', () => {
    const originalPlatform = process.platform;
    const originalArch = process.arch;
    Object.defineProperties(process, {
      platform: { value: 'darwin', configurable: true },
      arch: { value: 'riscv64', configurable: true },
    });
    try {
      expect(() =>
        (updateManager as unknown as { getPlatformKey: () => string }).getPlatformKey(),
      ).toThrow('Unsupported platform: darwin-riscv64');
    } finally {
      Object.defineProperties(process, {
        platform: { value: originalPlatform, configurable: true },
        arch: { value: originalArch, configurable: true },
      });
    }
  });

  it('throws error when server returns 500', async () => {
    vi.mocked(fetch).mockResolvedValue(createResponse(500, {}));

    await expect(updateManager.checkForUpdates()).rejects.toThrow('Server returned 500');
  });

  it('rejects downloadUpdate before an available update check', async () => {
    await expect(updateManager.downloadUpdate()).rejects.toThrow('No update is available');

    vi.mocked(fetch).mockResolvedValue(createResponse(200, createManifest('1.0.0')));
    await updateManager.checkForUpdates();

    await expect(updateManager.downloadUpdate()).rejects.toThrow('No update is available');
    expect(updater.downloadUpdate).not.toHaveBeenCalled();
  });

  it('configures a generic feed and calls updater methods in order', async () => {
    vi.mocked(fetch).mockResolvedValue(createResponse(200, createManifest('1.3.0')));
    await updateManager.checkForUpdates();

    const callOrder: string[] = [];
    updater.setFeedURL.mockImplementation(() => callOrder.push('setFeedURL'));
    updater.checkForUpdates.mockImplementation(async () => {
      callOrder.push('checkForUpdates');
      return {
        updateInfo: {
          version: '1.3.0',
          files: [
            {
              url: 'https://updates.sage.app/releases/1.3.0/Sage-Setup-1.3.0.bin',
              sha512: 'a'.repeat(128),
              size: 104857600,
            },
          ],
        },
      };
    });
    updater.downloadUpdate.mockImplementation(async () => {
      callOrder.push('downloadUpdate');
      return [];
    });

    await updateManager.downloadUpdate();

    expect(updater.setFeedURL).toHaveBeenCalledWith({
      provider: 'generic',
      url: 'https://updates.sage.app/releases/1.3.0/',
      channel: 'latest',
    });
    expect(callOrder).toEqual(['setFeedURL', 'checkForUpdates', 'downloadUpdate']);
  });

  it.each([
    ['beta', 'beta'],
    ['alpha', 'alpha'],
  ] as const)('preserves the %s channel for updater metadata', async (channel, updaterChannel) => {
    await fs.writeFile(
      `${mockUserData}/update-config.json`,
      JSON.stringify({
        updateStrategy: 'manual',
        channel,
        rollbackWindowDays: 7,
        autoRollbackThreshold: 3,
        checkIntervalHours: 24,
        updateServerUrl: 'https://updates.sage.app',
        enableTelemetry: false,
        cacheRetentionDays: 30,
      }),
    );
    vi.mocked(fetch).mockResolvedValue(createResponse(200, createManifest('1.3.0', { channel })));
    await updateManager.checkForUpdates();

    await updateManager.downloadUpdate();

    expect(updater.setFeedURL).toHaveBeenCalledWith({
      provider: 'generic',
      url: 'https://updates.sage.app/releases/1.3.0/',
      channel: updaterChannel,
    });
  });

  it('does not persist pendingUpdate when updater reports no matching update', async () => {
    vi.mocked(fetch).mockResolvedValue(createResponse(200, createManifest('1.3.0')));
    await updateManager.checkForUpdates();
    updater.checkForUpdates.mockResolvedValue(null);

    await expect(updateManager.downloadUpdate()).rejects.toThrow(
      'Updater metadata does not match the checked update',
    );
    expect(updater.downloadUpdate).not.toHaveBeenCalled();
    const state = JSON.parse(await fs.readFile(`${mockUserData}/update-state.json`, 'utf8'));
    expect(state.pendingUpdate).toBeNull();
  });

  it('does not persist pendingUpdate when updater metadata check fails', async () => {
    vi.mocked(fetch).mockResolvedValue(createResponse(200, createManifest('1.3.0')));
    await updateManager.checkForUpdates();
    updater.checkForUpdates.mockRejectedValue(new Error('metadata unavailable'));

    await expect(updateManager.downloadUpdate()).rejects.toThrow(
      'Failed to download update: metadata unavailable',
    );
    const state = JSON.parse(await fs.readFile(`${mockUserData}/update-state.json`, 'utf8'));
    expect(state.pendingUpdate).toBeNull();
  });

  it.each([
    ['version', { version: '1.3.1' }],
    [
      'filename',
      {
        files: [
          {
            url: 'https://updates.sage.app/releases/1.3.0/other.bin',
            sha512: 'a'.repeat(128),
            size: 104857600,
          },
        ],
      },
    ],
    [
      'sha512',
      {
        files: [
          {
            url: 'https://updates.sage.app/releases/1.3.0/Sage-Setup-1.3.0.bin',
            sha512: 'b'.repeat(128),
            size: 104857600,
          },
        ],
      },
    ],
    [
      'size',
      {
        files: [
          {
            url: 'https://updates.sage.app/releases/1.3.0/Sage-Setup-1.3.0.bin',
            sha512: 'a'.repeat(128),
            size: 1,
          },
        ],
      },
    ],
  ])('rejects updater metadata with mismatched %s', async (_field, updateInfo) => {
    vi.mocked(fetch).mockResolvedValue(createResponse(200, createManifest('1.3.0')));
    await updateManager.checkForUpdates();
    updater.checkForUpdates.mockResolvedValue({ updateInfo });

    await expect(updateManager.downloadUpdate()).rejects.toThrow(
      'Updater metadata does not match the checked update',
    );
    expect(updater.downloadUpdate).not.toHaveBeenCalled();
  });

  it('accepts relative artifact basenames from updater metadata', async () => {
    vi.mocked(fetch).mockResolvedValue(createResponse(200, createManifest('1.3.0')));
    await updateManager.checkForUpdates();
    updater.checkForUpdates.mockResolvedValue({
      updateInfo: {
        version: '1.3.0',
        files: [
          {
            url: 'Sage-Setup-1.3.0.bin',
            sha512: 'a'.repeat(128),
            size: 104857600,
          },
        ],
      },
    });

    await expect(updateManager.downloadUpdate()).resolves.toBeUndefined();
  });

  it('accepts URL-encoded artifact basenames from updater metadata', async () => {
    const manifest = createManifest('1.3.0');
    (manifest.files as Record<string, Record<string, unknown>>)[platformKey].filename =
      'Sage Setup 1.3.0.bin';
    vi.mocked(fetch).mockResolvedValue(createResponse(200, manifest));
    await updateManager.checkForUpdates();
    updater.checkForUpdates.mockResolvedValue({
      updateInfo: {
        version: '1.3.0',
        files: [
          {
            url: 'https://updates.sage.app/releases/1.3.0/Sage%20Setup%201.3.0.bin',
            sha512: 'a'.repeat(128),
            size: 104857600,
          },
        ],
      },
    });

    await expect(updateManager.downloadUpdate()).resolves.toBeUndefined();
  });

  it('persists pendingUpdate after a successful download', async () => {
    vi.mocked(fetch).mockResolvedValue(createResponse(200, createManifest('1.3.0')));
    await updateManager.checkForUpdates();

    const before = Date.now();
    await updateManager.downloadUpdate();
    const after = Date.now();
    const state = JSON.parse(await fs.readFile(`${mockUserData}/update-state.json`, 'utf8'));

    expect(state.pendingUpdate.version).toBe('1.3.0');
    expect(Date.parse(state.pendingUpdate.downloadedAt)).toBeGreaterThanOrEqual(before);
    expect(Date.parse(state.pendingUpdate.downloadedAt)).toBeLessThanOrEqual(after);
  });

  it('keeps pendingUpdate valid when downloading the same checked update twice', async () => {
    vi.mocked(fetch).mockResolvedValue(createResponse(200, createManifest('1.3.0')));
    await updateManager.checkForUpdates();

    await updateManager.downloadUpdate();
    const firstState = JSON.parse(await fs.readFile(`${mockUserData}/update-state.json`, 'utf8'));
    await updateManager.downloadUpdate();
    const secondState = JSON.parse(await fs.readFile(`${mockUserData}/update-state.json`, 'utf8'));

    expect(updater.downloadUpdate).toHaveBeenCalledTimes(2);
    expect(secondState.pendingUpdate.version).toBe('1.3.0');
    expect(Date.parse(secondState.pendingUpdate.downloadedAt)).not.toBeNaN();
    expect(Date.parse(secondState.pendingUpdate.downloadedAt)).toBeGreaterThanOrEqual(
      Date.parse(firstState.pendingUpdate.downloadedAt),
    );
  });

  it('does not persist pendingUpdate when download fails', async () => {
    vi.mocked(fetch).mockResolvedValue(createResponse(200, createManifest('1.3.0')));
    await updateManager.checkForUpdates();
    updater.downloadUpdate.mockRejectedValue(new Error('network unavailable'));

    await expect(updateManager.downloadUpdate()).rejects.toThrow(
      'Failed to download update: network unavailable',
    );
    const state = JSON.parse(await fs.readFile(`${mockUserData}/update-state.json`, 'utf8'));
    expect(state.pendingUpdate).toBeNull();
  });

  it('forwards download progress and removes the listener when unsubscribed', async () => {
    const progressHandler = vi.fn();
    const unsubscribe = updateManager.onDownloadProgress(progressHandler);
    const updaterListener = updater.on.mock.calls[0]?.[1] as
      | ((event: { percent: number }) => void)
      | undefined;

    expect(updater.on).toHaveBeenCalledWith('download-progress', expect.any(Function));
    updaterListener?.({ percent: 42.5 });
    expect(progressHandler).toHaveBeenCalledWith(42.5);

    unsubscribe();
    expect(updater.off).toHaveBeenCalledWith('download-progress', expect.any(Function));
  });

  describe('installUpdate', () => {
    const tempInstallRoot = '/tmp/test-install-root-task6';
    const tempInstallDir = `${tempInstallRoot}/app`;
    const tempPrevDir = `${tempInstallRoot}/.prev`;
    const tempBatScript = `${tempInstallRoot}/.prepare-rollback.bat`;
    let originalExecPath: string;
    let originalPlatform: PropertyDescriptor | undefined;

    beforeEach(async () => {
      originalExecPath = process.execPath;
      originalPlatform = Object.getOwnPropertyDescriptor(process, 'platform');
      Object.defineProperty(process, 'execPath', {
        value: `${tempInstallDir}/Sage`,
        configurable: true,
      });
      await fs.rm(tempInstallRoot, { recursive: true, force: true });
      await fs.mkdir(tempInstallDir, { recursive: true });
    });

    afterEach(async () => {
      Object.defineProperty(process, 'execPath', {
        value: originalExecPath,
        configurable: true,
      });
      if (originalPlatform) {
        Object.defineProperty(process, 'platform', originalPlatform);
      }
      await fs.rm(tempInstallRoot, { recursive: true, force: true });
    });

    async function seedPendingUpdate(
      version: string | null,
      overrides: Record<string, unknown> = {},
    ): Promise<void> {
      const stateManager = new StateManager();
      const base = await stateManager.getState();
      await stateManager.setState({
        ...base,
        ...overrides,
        pendingUpdate:
          version === null ? null : { version, downloadedAt: new Date().toISOString() },
      });
    }

    it('throws when no pending update exists', async () => {
      await seedPendingUpdate(null);

      await expect(updateManager.installUpdate()).rejects.toThrow('No pending update to install');
      expect(updater.quitAndInstall).not.toHaveBeenCalled();
    });

    it('calls quitAndInstall after preparing for upgrade', async () => {
      await seedPendingUpdate('1.3.0');

      await updateManager.installUpdate();

      expect(updater.quitAndInstall).toHaveBeenCalledTimes(1);
    });

    it('updates state with new version and preserves the old as lastKnownGood', async () => {
      await seedPendingUpdate('1.3.0');

      await updateManager.installUpdate();

      const state = JSON.parse(await fs.readFile(`${mockUserData}/update-state.json`, 'utf8'));
      expect(state.currentVersion).toBe('1.3.0');
      expect(state.lastKnownGoodVersion).toBe('1.0.0');
      expect(state.pendingUpdate).toBeNull();
      expect(state.crashCount).toBe(0);
      expect(Date.parse(state.lastKnownGoodInstallDate)).not.toBeNaN();
    });

    it('sets lastKnownGoodInstallDate to a recent ISO timestamp', async () => {
      await seedPendingUpdate('1.3.0');

      const before = Date.now();
      await updateManager.installUpdate();
      const after = Date.now();

      const state = JSON.parse(await fs.readFile(`${mockUserData}/update-state.json`, 'utf8'));
      const recorded = Date.parse(state.lastKnownGoodInstallDate);
      expect(recorded).toBeGreaterThanOrEqual(before);
      expect(recorded).toBeLessThanOrEqual(after);
    });

    it('writes a .prepare-rollback.bat on Windows', async () => {
      Object.defineProperty(process, 'platform', { value: 'win32', configurable: true });
      await seedPendingUpdate('1.3.0');

      await updateManager.installUpdate();

      const batContent = await fs.readFile(tempBatScript, 'utf8');
      expect(batContent).toContain('@echo off');
      expect(batContent).toContain('timeout /t 2');
      expect(batContent).toContain('move /y');
      expect(batContent).toContain(tempInstallDir);
      expect(batContent).toContain('.prev');
      expect(updater.quitAndInstall).toHaveBeenCalled();
    });

    it('renames the install directory on non-Windows platforms', async () => {
      Object.defineProperty(process, 'platform', { value: 'linux', configurable: true });
      await seedPendingUpdate('1.3.0');

      await updateManager.installUpdate();

      await expect(fs.access(tempInstallDir)).rejects.toThrow();
      await expect(fs.access(tempPrevDir)).resolves.toBeUndefined();
      expect(updater.quitAndInstall).toHaveBeenCalled();
    });

    it('removes a stale .prev directory before creating a new one', async () => {
      Object.defineProperty(process, 'platform', { value: 'linux', configurable: true });
      await fs.mkdir(tempPrevDir, { recursive: true });
      await fs.writeFile(`${tempPrevDir}/marker.txt`, 'stale');
      await seedPendingUpdate('1.3.0');

      await updateManager.installUpdate();

      const markerExists = await fs.access(`${tempPrevDir}/marker.txt`).then(
        () => true,
        () => false,
      );
      expect(markerExists).toBe(false);
    });
  });

  describe('onAppStartup', () => {
    function createVisibleWindow(): object {
      return {
        isDestroyed: () => false,
        isVisible: () => true,
      };
    }

    async function readState(): Promise<Record<string, unknown>> {
      const data = await fs.readFile(`${mockUserData}/update-state.json`, 'utf8');
      return JSON.parse(data);
    }

    beforeEach(() => {
      mockRunPostStartupChecks = vi.fn();
    });

    it('resets crash count when version changes', async () => {
      mockRunPostStartupChecks.mockResolvedValue({
        passed: true,
        details: [],
      });

      const stateManager = new StateManager();
      const base = await stateManager.getState();
      await stateManager.setState({
        ...base,
        currentVersion: '1.1.0',
        lastRecordedVersion: '1.0.0',
        crashCount: 2,
      });

      await updateManager.onAppStartup(() => createVisibleWindow() as Electron.BrowserWindow);

      const state = await readState();
      expect(state.crashCount).toBe(0);
      expect(state.lastRecordedVersion).toBe('1.1.0');
    });

    it('increments crash count when health checks fail', async () => {
      mockRunPostStartupChecks.mockResolvedValue({
        passed: false,
        details: [{ name: 'backend', passed: false, error: 'unhealthy' }],
      });

      const stateManager = new StateManager();
      const base = await stateManager.getState();
      await stateManager.setState({
        ...base,
        crashCount: 0,
        lastRecordedVersion: base.currentVersion,
      });

      await expect(
        updateManager.onAppStartup(() => createVisibleWindow() as Electron.BrowserWindow),
      ).rejects.toThrow('Health check failed');

      const state = await readState();
      expect(state.crashCount).toBe(1);
    });

    it('triggers rollback when crash count reaches threshold', async () => {
      mockRunPostStartupChecks.mockResolvedValue({
        passed: false,
        details: [{ name: 'backend', passed: false, error: 'unhealthy' }],
      });

      const stateManager = new StateManager();
      const base = await stateManager.getState();
      await stateManager.setState({
        ...base,
        crashCount: 2,
        lastRecordedVersion: base.currentVersion,
        lastKnownGoodVersion: '0.9.0',
      });

      // Mock rollback to avoid actual rollback execution
      const rollbackSpy = vi.spyOn(updateManager, 'rollback').mockResolvedValue(undefined);

      await updateManager.onAppStartup(() => createVisibleWindow() as Electron.BrowserWindow);

      expect(rollbackSpy).toHaveBeenCalledWith('auto-rollback:health-check-failed');

      const state = await readState();
      expect(state.crashCount).toBe(3);

      rollbackSpy.mockRestore();
    });

    it('resets crash count to 0 when health checks pass after prior failures', async () => {
      mockRunPostStartupChecks.mockResolvedValue({
        passed: true,
        details: [],
      });

      const stateManager = new StateManager();
      const base = await stateManager.getState();
      await stateManager.setState({
        ...base,
        crashCount: 2,
        lastRecordedVersion: base.currentVersion,
      });

      await updateManager.onAppStartup(() => createVisibleWindow() as Electron.BrowserWindow);

      const state = await readState();
      expect(state.crashCount).toBe(0);
    });

    it('preserves crash count when version is unchanged and checks fail', async () => {
      mockRunPostStartupChecks.mockResolvedValue({
        passed: false,
        details: [{ name: 'backend', passed: false, error: 'unhealthy' }],
      });

      const stateManager = new StateManager();
      const base = await stateManager.getState();
      await stateManager.setState({
        ...base,
        crashCount: 1,
        lastRecordedVersion: base.currentVersion,
      });

      await expect(
        updateManager.onAppStartup(() => createVisibleWindow() as Electron.BrowserWindow),
      ).rejects.toThrow('Health check failed');

      const state = await readState();
      // Was 1, incremented to 2 (version did not change, so no reset)
      expect(state.crashCount).toBe(2);
    });
  });

  describe('rollback', () => {
    const tempInstallRoot = '/tmp/test-install-root-rollback';
    const tempInstallDir = `${tempInstallRoot}/app`;
    const tempPrevDir = `${tempInstallRoot}/.prev`;
    let originalExecPath: string;

    beforeEach(async () => {
      originalExecPath = process.execPath;
      Object.defineProperty(process, 'execPath', {
        value: `${tempInstallDir}/Sage`,
        configurable: true,
      });
      await fs.rm(tempInstallRoot, { recursive: true, force: true });
      await fs.mkdir(tempInstallDir, { recursive: true });
      // Clear app mocks
      const { app } = await import('electron');
      vi.mocked(app.relaunch).mockClear();
      vi.mocked(app.exit).mockClear();
    });

    afterEach(async () => {
      Object.defineProperty(process, 'execPath', {
        value: originalExecPath,
        configurable: true,
      });
      await fs.rm(tempInstallRoot, { recursive: true, force: true });
    });

    it('restores .prev directory and updates state', async () => {
      // Setup: create .prev directory
      await fs.mkdir(tempPrevDir, { recursive: true });
      await fs.writeFile(`${tempPrevDir}/marker.txt`, 'previous version');

      // Seed state
      const stateManager = new StateManager();
      const base = await stateManager.getState();
      await stateManager.setState({
        ...base,
        currentVersion: '1.3.0',
        lastKnownGoodVersion: '1.0.0',
        crashCount: 3,
      });

      // Mock fetch to ignore the rollback event report
      vi.mocked(fetch).mockResolvedValue({ ok: true } as Response);

      await updateManager.rollback('test-rollback');

      // Verify .prev was renamed to install dir
      await expect(fs.access(tempInstallDir)).resolves.toBeUndefined();
      await expect(fs.access(tempPrevDir)).rejects.toThrow();

      // Verify marker file is preserved
      const marker = await fs.readFile(`${tempInstallDir}/marker.txt`, 'utf8');
      expect(marker).toBe('previous version');

      // Verify state was updated
      const state = JSON.parse(await fs.readFile(`${mockUserData}/update-state.json`, 'utf8'));
      expect(state.currentVersion).toBe('1.0.0');
      expect(state.crashCount).toBe(0);
    });

    it('calls app.relaunch and app.exit after rollback', async () => {
      await fs.mkdir(tempPrevDir, { recursive: true });
      vi.mocked(fetch).mockResolvedValue({ ok: true } as Response);

      const { app } = await import('electron');
      const mockApp = vi.mocked(app);

      await updateManager.rollback('test-rollback');

      expect(mockApp.relaunch).toHaveBeenCalledTimes(1);
      expect(mockApp.exit).toHaveBeenCalledWith(0);
    });

    it('reports rollback event to backend', async () => {
      await fs.mkdir(tempPrevDir, { recursive: true });
      const fetchMock = vi.mocked(fetch).mockResolvedValue({ ok: true } as Response);

      const stateManager = new StateManager();
      const base = await stateManager.getState();
      await stateManager.setState({
        ...base,
        currentVersion: '1.3.0',
        lastKnownGoodVersion: '1.0.0',
        crashCount: 3,
      });

      await updateManager.rollback('test-reason');

      expect(fetchMock).toHaveBeenCalledWith(
        'https://updates.sage.app/api/v1/updates/rollbacks',
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        }),
      );

      const callBody = JSON.parse(fetchMock.mock.calls[0][1]?.body as string);
      expect(callBody).toMatchObject({
        from_version: '1.3.0',
        to_version: '1.0.0',
        reason: 'test-reason',
        crash_count: 3,
      });
      expect(callBody.timestamp).toEqual(expect.any(String));
    });

    it('ignores rollback event reporting failures', async () => {
      await fs.mkdir(tempPrevDir, { recursive: true });
      vi.mocked(fetch).mockRejectedValue(new Error('network error'));

      // Should not throw
      await expect(updateManager.rollback('test-rollback')).resolves.toBeUndefined();
    });
  });

  describe('rollback with package reinstall', () => {
    const tempInstallRoot = '/tmp/test-install-root-reinstall';
    const tempInstallDir = `${tempInstallRoot}/app`;
    let originalExecPath: string;

    beforeEach(async () => {
      originalExecPath = process.execPath;
      Object.defineProperty(process, 'execPath', {
        value: `${tempInstallDir}/Sage.exe`,
        configurable: true,
      });
      await fs.rm(tempInstallRoot, { recursive: true, force: true });
      await fs.mkdir(tempInstallDir, { recursive: true });
      // Clear app mocks
      const { app } = await import('electron');
      vi.mocked(app.relaunch).mockClear();
      vi.mocked(app.exit).mockClear();
    });

    afterEach(async () => {
      Object.defineProperty(process, 'execPath', {
        value: originalExecPath,
        configurable: true,
      });
      await fs.rm(tempInstallRoot, { recursive: true, force: true });
    });

    it('throws when no cached package exists', async () => {
      // No .prev, no cached package
      const stateManager = new StateManager();
      const base = await stateManager.getState();
      await stateManager.setState({
        ...base,
        lastKnownGoodVersion: '1.0.0',
      });

      vi.mocked(fetch).mockResolvedValue({ ok: true } as Response);

      await expect(updateManager.rollback('test-rollback')).rejects.toThrow(
        'No rollback package available',
      );
    });

    it('spawns installer from cached package', async () => {
      // Create cached package
      const cacheDir = `${mockUserData}/updates/cache`;
      await fs.mkdir(cacheDir, { recursive: true });
      await fs.writeFile(`${cacheDir}/Sage-Setup-1.0.0.exe`, 'fake installer');

      const stateManager = new StateManager();
      const base = await stateManager.getState();
      await stateManager.setState({
        ...base,
        lastKnownGoodVersion: '1.0.0',
      });

      vi.mocked(fetch).mockResolvedValue({ ok: true } as Response);

      // Mock child_process.spawn
      const mockSpawn = vi.fn().mockReturnValue({
        on: (event: string, callback: (code: number) => void) => {
          if (event === 'exit') {
            setTimeout(() => callback(0), 0);
          }
        },
      });

      vi.doMock('child_process', () => ({ spawn: mockSpawn }));

      // Need to re-import to pick up the mock
      const { UpdateManager: FreshUpdateManager } = await import('../updateManager');
      const freshManager = new FreshUpdateManager(updater);

      const { app } = await import('electron');
      const mockApp = vi.mocked(app);

      await freshManager.rollback('test-rollback');

      expect(mockSpawn).toHaveBeenCalledWith(`${cacheDir}/Sage-Setup-1.0.0.exe`, [
        '/S',
        `/D=${tempInstallDir}`,
      ]);
      expect(mockApp.relaunch).toHaveBeenCalled();
      expect(mockApp.exit).toHaveBeenCalledWith(0);

      vi.doUnmock('child_process');
    });

    it('throws when installer exits with non-zero code', async () => {
      const cacheDir = `${mockUserData}/updates/cache`;
      await fs.mkdir(cacheDir, { recursive: true });
      await fs.writeFile(`${cacheDir}/Sage-Setup-1.0.0.exe`, 'fake installer');

      const stateManager = new StateManager();
      const base = await stateManager.getState();
      await stateManager.setState({
        ...base,
        lastKnownGoodVersion: '1.0.0',
      });

      vi.mocked(fetch).mockResolvedValue({ ok: true } as Response);

      const mockSpawn = vi.fn().mockReturnValue({
        on: (event: string, callback: (code: number) => void) => {
          if (event === 'exit') {
            setTimeout(() => callback(1), 0);
          }
        },
      });

      vi.doMock('child_process', () => ({ spawn: mockSpawn }));

      const { UpdateManager: FreshUpdateManager } = await import('../updateManager');
      const freshManager = new FreshUpdateManager(updater);

      await expect(freshManager.rollback('test-rollback')).rejects.toThrow(
        'Installer exited with code 1',
      );

      vi.doUnmock('child_process');
    });
  });

  describe('canManualRollback', () => {
    it('returns allowed: true when conditions are met', async () => {
      const stateManager = new StateManager();
      const base = await stateManager.getState();
      await stateManager.setState({
        ...base,
        currentVersion: '1.3.0',
        lastKnownGoodVersion: '1.0.0',
        lastKnownGoodInstallDate: new Date().toISOString(),
      });

      const result = await updateManager.canManualRollback();

      expect(result.allowed).toBe(true);
    });

    it('returns allowed: false when no lastKnownGoodVersion', async () => {
      const stateManager = new StateManager();
      const base = await stateManager.getState();
      await stateManager.setState({
        ...base,
        lastKnownGoodVersion: '',
      });

      const result = await updateManager.canManualRollback();

      expect(result.allowed).toBe(false);
      expect(result.reason).toBe('No known stable version available');
    });

    it('returns allowed: false when already on stable version', async () => {
      const stateManager = new StateManager();
      const base = await stateManager.getState();
      await stateManager.setState({
        ...base,
        currentVersion: '1.0.0',
        lastKnownGoodVersion: '1.0.0',
      });

      const result = await updateManager.canManualRollback();

      expect(result.allowed).toBe(false);
      expect(result.reason).toBe('Already on stable version');
    });

    it('returns allowed: false when rollback window expired', async () => {
      const stateManager = new StateManager();
      const base = await stateManager.getState();
      const eightDaysAgo = new Date(Date.now() - 8 * 24 * 60 * 60 * 1000).toISOString();
      await stateManager.setState({
        ...base,
        currentVersion: '1.3.0',
        lastKnownGoodVersion: '1.0.0',
        lastKnownGoodInstallDate: eightDaysAgo,
      });

      const result = await updateManager.canManualRollback();

      expect(result.allowed).toBe(false);
      expect(result.reason).toContain('Rollback window closed');
    });

    it('returns allowed: false when install date is unknown', async () => {
      const stateManager = new StateManager();
      const base = await stateManager.getState();
      await stateManager.setState({
        ...base,
        currentVersion: '1.3.0',
        lastKnownGoodVersion: '1.0.0',
        lastKnownGoodInstallDate: '',
      });

      const result = await updateManager.canManualRollback();

      expect(result.allowed).toBe(false);
      expect(result.reason).toBe('Rollback window unknown');
    });
  });

  describe('setChannel', () => {
    it('invalidates cached check result when channel changes', async () => {
      vi.mocked(fetch).mockResolvedValue(createResponse(404, {}));
      await updateManager.checkForUpdates();

      await updateManager.setChannel('beta');

      const state = await updateManager.canManualRollback();
      expect(state.allowed).toBe(false);

      const config = await updateManager.getConfig();
      expect(config.channel).toBe('beta');

      const downloadResult = updateManager.downloadUpdate();
      await expect(downloadResult).rejects.toThrow('No update is available to download');
    });
  });
});
