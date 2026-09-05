/**
 * Integration tests for the update system end-to-end upgrade flow.
 *
 * These tests wire together REAL StateManager, ConfigManager, and UpdateManager
 * components while mocking external dependencies (electron-updater, fetch, fs
 * for install/rollback directories, and the health checker).
 *
 * The goal is to verify that multiple subsystems interact correctly across
 * complete upgrade scenarios — check → download → install, auto-strategies,
 * health-check-driven rollback, manual rollback, and channel switching.
 */
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import * as fs from 'fs/promises';
import * as os from 'os';
import * as path from 'path';

// ─── Platform key (must be determined before mock factories) ──────────────────
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

// ─── Shared mutable state ─────────────────────────────────────────────────────
let mockUserData: string | undefined;
let mockInstallRoot: string | undefined;

// ─── Mock factories ───────────────────────────────────────────────────────────
vi.mock('electron', () => ({
  app: {
    getPath: (name: string) => {
      if (name === 'userData') {
        if (!mockUserData) throw new Error('Test userData directory is not initialized');
        return mockUserData;
      }
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

// vi.hoisted() runs before vi.mock/vi.doMock factory evaluation, ensuring the
// mock function is available when the factory captures it by reference.
const { mockRunPostStartupChecks } = vi.hoisted(() => ({
  mockRunPostStartupChecks: vi.fn().mockResolvedValue({ passed: true, details: [] }),
}));

vi.mock('../updateHealthChecker', () => ({
  LauncherHealthChecker: vi.fn().mockImplementation(() => ({
    runPostStartupChecks: mockRunPostStartupChecks,
  })),
}));

// ─── Helpers ──────────────────────────────────────────────────────────────────
function createResponse(status: number, body: unknown): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
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
  } = {},
): Record<string, unknown> {
  const channel = options.channel ?? 'stable';
  return {
    version,
    channel,
    release_date: '2026-09-05T12:00:00Z',
    release_notes: '## New features and improvements',
    min_upgradable_version: options.minimum ?? '1.0.0',
    files: {
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
        version: '2.0.0',
        files: [
          {
            url: 'https://updates.sage.app/releases/2.0.0/Sage-Setup-2.0.0.bin',
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

function resetFakeUpdaterDefaults(updater: FakeUpdater): void {
  updater.checkForUpdates.mockReset().mockResolvedValue({
    updateInfo: {
      version: '2.0.0',
      files: [
        {
          url: 'https://updates.sage.app/releases/2.0.0/Sage-Setup-2.0.0.bin',
          sha512: 'a'.repeat(128),
          size: 104857600,
        },
      ],
    },
  });
  updater.downloadUpdate.mockReset().mockResolvedValue([]);
  updater.setFeedURL.mockClear();
  updater.quitAndInstall.mockClear();
  updater.on.mockClear();
  updater.off.mockClear();
}

// ─── Dynamic imports (after vi.mock / vi.doMock) ─────────────────────────────
const { UpdateManager } = await import('../updateManager');
const { StateManager } = await import('../updateState');
const { ConfigManager } = await import('../updateConfig');

// ─── Test suite ───────────────────────────────────────────────────────────────
describe('Update System Integration', () => {
  let updateManager: InstanceType<typeof UpdateManager>;
  let configManager: InstanceType<typeof ConfigManager>;
  let updater: FakeUpdater;
  let originalExecPath: string | undefined;

  beforeEach(async () => {
    vi.clearAllMocks();
    mockRunPostStartupChecks.mockResolvedValue({ passed: true, details: [] });

    // Fresh temp directories per test. Keep each path undefined until its
    // mkdtemp call succeeds so cleanup can never target a guessed path.
    mockUserData = await fs.mkdtemp(path.join(os.tmpdir(), 'update-integ-state-'));
    try {
      mockInstallRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'update-integ-install-'));
    } catch (error) {
      await fs.rm(mockUserData, { recursive: true, force: true });
      mockUserData = undefined;
      throw error;
    }

    updater = createFakeUpdater();
    resetFakeUpdaterDefaults(updater);

    updateManager = new UpdateManager(updater);
    configManager = new ConfigManager();
    await configManager.getConfig();

    vi.stubGlobal('fetch', vi.fn());
    vi.mocked(fetch).mockResolvedValue({ ok: true } as Response);
  });

  afterEach(async () => {
    vi.unstubAllGlobals();

    if (originalExecPath !== undefined) {
      Object.defineProperty(process, 'execPath', {
        value: originalExecPath,
        configurable: true,
      });
      originalExecPath = undefined;
    }

    if (mockUserData !== undefined) {
      await fs.rm(mockUserData, { recursive: true, force: true });
      mockUserData = undefined;
    }
    if (mockInstallRoot !== undefined) {
      await fs.rm(mockInstallRoot, { recursive: true, force: true });
      mockInstallRoot = undefined;
    }
  });

  // ── Shared helpers ────────────────────────────────────────────────────────
  async function readState(): Promise<Record<string, unknown>> {
    if (!mockUserData) throw new Error('Test userData directory is not initialized');
    const data = await fs.readFile(path.join(mockUserData, 'update-state.json'), 'utf8');
    return JSON.parse(data);
  }

  async function readConfig(): Promise<Record<string, unknown>> {
    if (!mockUserData) throw new Error('Test userData directory is not initialized');
    const data = await fs.readFile(path.join(mockUserData, 'update-config.json'), 'utf8');
    return JSON.parse(data);
  }

  function useTempInstallDir(): { installDir: string; prevDir: string } {
    if (!mockInstallRoot) throw new Error('Test install directory is not initialized');
    const installDir = path.join(mockInstallRoot, 'app');
    const prevDir = path.join(mockInstallRoot, '.prev');

    originalExecPath = process.execPath;
    Object.defineProperty(process, 'execPath', {
      value: path.join(installDir, 'Sage'),
      configurable: true,
    });

    return { installDir, prevDir };
  }

  function createVisibleWindow(): object {
    return { isDestroyed: () => false, isVisible: () => true };
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Scenario 1: Manual update flow (Happy Path)
  // ─────────────────────────────────────────────────────────────────────────
  describe('Scenario 1: Manual update flow', () => {
    it('checks → downloads → installs → restarts', async () => {
      // Configure manual strategy
      await updateManager.setStrategy('manual');

      // Mock server manifest advertising v2.0.0
      vi.mocked(fetch).mockResolvedValue(createResponse(200, createManifest('2.0.0')));

      // Step 1 — check for updates
      const checkResult = await updateManager.checkForUpdates();
      expect(checkResult.updateAvailable).toBe(true);
      expect(checkResult.version).toBe('2.0.0');
      expect(checkResult.releaseNotes).toBe('## New features and improvements');

      // Verify state persisted by check
      let state = await readState();
      expect(state.updateAvailable).toBe(true);
      expect((state.availableUpdate as { version: string }).version).toBe('2.0.0');
      expect(state.lastCheckTime).toEqual(expect.any(String));

      // Step 2 — download update
      await updateManager.downloadUpdate();

      // Verify updater was configured correctly
      expect(updater.setFeedURL).toHaveBeenCalledWith({
        provider: 'generic',
        url: 'https://updates.sage.app/releases/2.0.0/',
        channel: 'latest',
      });
      expect(updater.downloadUpdate).toHaveBeenCalled();

      // Verify state persisted by download
      state = await readState();
      expect(state.pendingUpdate).not.toBeNull();
      expect((state.pendingUpdate as { version: string }).version).toBe('2.0.0');
      expect(
        Date.parse((state.pendingUpdate as { downloadedAt: string }).downloadedAt),
      ).not.toBeNaN();
      expect(state.updateAvailable).toBe(false);

      // Step 3 — install update (uses temp install dir for prepareForUpgrade)
      const { installDir, prevDir } = useTempInstallDir();
      await fs.mkdir(installDir, { recursive: true });

      await updateManager.installUpdate();

      // Verify quitAndInstall was called (simulates restart)
      expect(updater.quitAndInstall).toHaveBeenCalledTimes(1);

      // Verify state reflects the new version
      state = await readState();
      expect(state.currentVersion).toBe('2.0.0');
      expect(state.lastKnownGoodVersion).toBe('1.0.0');
      expect(state.crashCount).toBe(0);
      expect(state.pendingUpdate).toBeNull();
      expect(Date.parse(state.lastKnownGoodInstallDate as string)).not.toBeNaN();

      // Verify prepareForUpgrade renamed install dir → .prev (non-Windows)
      if (process.platform !== 'win32') {
        await expect(fs.access(installDir)).rejects.toThrow();
        await expect(fs.access(prevDir)).resolves.toBeUndefined();
      }
    });

    it('notifies state-change listeners through the full flow', async () => {
      await updateManager.setStrategy('manual');
      vi.mocked(fetch).mockResolvedValue(createResponse(200, createManifest('2.0.0')));

      const events: string[] = [];
      updateManager.onStateChange((s) => {
        if (s.updateAvailable) events.push('check-available');
        if (s.pendingUpdate) events.push('downloaded');
        if (s.currentVersion === '2.0.0') events.push('installed');
      });

      await updateManager.checkForUpdates();
      const { installDir } = useTempInstallDir();
      await fs.mkdir(installDir, { recursive: true });
      await updateManager.downloadUpdate();
      await updateManager.installUpdate();

      expect(events).toEqual(['check-available', 'downloaded', 'installed']);
    });
  });

  // ─────────────────────────────────────────────────────────────────────────
  // Scenario 2: Auto-download strategy
  // ─────────────────────────────────────────────────────────────────────────
  describe('Scenario 2: Auto-download strategy', () => {
    it('persists auto-download config and orchestrates check → download', async () => {
      // Config: auto-download
      await updateManager.setStrategy('auto-download');
      const config = await updateManager.getConfig();
      expect(config.updateStrategy).toBe('auto-download');

      // Mock server manifest
      vi.mocked(fetch).mockResolvedValue(createResponse(200, createManifest('2.0.0')));

      // check returns update available; production orchestration auto-downloads
      const checkResult = await updateManager.checkForUpdates();
      expect(checkResult.updateAvailable).toBe(true);
      expect(checkResult.version).toBe('2.0.0');

      // Verify download completed automatically
      expect(updater.downloadUpdate).toHaveBeenCalled();
      const state = await readState();
      expect(state.pendingUpdate).not.toBeNull();
      expect((state.pendingUpdate as { version: string }).version).toBe('2.0.0');
      expect(
        Date.parse((state.pendingUpdate as { downloadedAt: string }).downloadedAt),
      ).not.toBeNaN();

      // Config persisted
      const savedConfig = await readConfig();
      expect(savedConfig.updateStrategy).toBe('auto-download');
    });

    it('keeps the update pending until user confirms install', async () => {
      await updateManager.setStrategy('auto-download');
      vi.mocked(fetch).mockResolvedValue(createResponse(200, createManifest('2.0.0')));

      await updateManager.checkForUpdates();

      // State should show pending update, NOT installed
      const state = await readState();
      expect(state.pendingUpdate).not.toBeNull();
      expect(state.currentVersion).toBe('1.0.0'); // not yet installed
      expect(state.lastKnownGoodVersion).toBe('1.0.0');
    });
  });

  // ─────────────────────────────────────────────────────────────────────────
  // Scenario 3: Auto-install strategy
  // ─────────────────────────────────────────────────────────────────────────
  describe('Scenario 3: Auto-install strategy', () => {
    it('persists auto-install config and orchestrates check → download → install', async () => {
      await updateManager.setStrategy('auto-install');

      const config = await updateManager.getConfig();
      expect(config.updateStrategy).toBe('auto-install');

      vi.mocked(fetch).mockResolvedValue(createResponse(200, createManifest('2.0.0')));

      // Prepare the install directory before check: auto-install runs as part
      // of checkForUpdates() and must move it to .prev during installation.
      const { installDir } = useTempInstallDir();
      await fs.mkdir(installDir, { recursive: true });

      // check triggers automatic download + install
      const checkResult = await updateManager.checkForUpdates();
      expect(checkResult.updateAvailable).toBe(true);

      // Verify full flow completed
      expect(updater.quitAndInstall).toHaveBeenCalled();

      const state = await readState();
      expect(state.currentVersion).toBe('2.0.0');
      expect(state.lastKnownGoodVersion).toBe('1.0.0');
      expect(state.crashCount).toBe(0);
      expect(state.pendingUpdate).toBeNull();
    });

    it('preserves the old version as lastKnownGood after auto-install', async () => {
      await updateManager.setStrategy('auto-install');
      vi.mocked(fetch).mockResolvedValue(createResponse(200, createManifest('2.0.0')));

      // Prepare install directory before the automatic install triggered by check.
      const { installDir } = useTempInstallDir();
      await fs.mkdir(installDir, { recursive: true });

      await updateManager.checkForUpdates();

      const state = await readState();
      expect(state.lastKnownGoodVersion).toBe('1.0.0');
      expect(state.lastKnownGoodInstallDate).toEqual(expect.any(String));
    });
  });

  // ─────────────────────────────────────────────────────────────────────────
  // Scenario 4: Health check failure → auto-rollback
  // ─────────────────────────────────────────────────────────────────────────
  describe('Scenario 4: Auto-rollback after health check failures', () => {
    it('triggers rollback after 3 consecutive failures', async () => {
      // Set up install directories for rollback (prepareForUpgrade + rollback)
      const { installDir, prevDir } = useTempInstallDir();
      await fs.mkdir(installDir, { recursive: true });
      await fs.mkdir(prevDir, { recursive: true });
      await fs.writeFile(path.join(prevDir, 'marker.txt'), 'previous-good-version');

      // Seed state: v2.0.0 installed, crashCount = 2, lastKnownGoodVersion = 1.0.0
      const stateManager = new StateManager();
      const baseState = await stateManager.getState();
      await stateManager.setState({
        ...baseState,
        currentVersion: '2.0.0',
        lastKnownGoodVersion: '1.0.0',
        lastKnownGoodInstallDate: new Date().toISOString(),
        crashCount: 2,
        lastRecordedVersion: '2.0.0',
      });

      // Mock fetch for rollback event report (non-blocking)
      vi.mocked(fetch).mockResolvedValue({ ok: true } as Response);

      // Mock health check to fail
      mockRunPostStartupChecks.mockResolvedValue({
        passed: false,
        details: [{ name: 'backend', passed: false, error: 'unhealthy' }],
      });

      // onAppStartup: health fails → crashCount 2→3 → threshold reached → rollback
      await updateManager.onAppStartup(() => createVisibleWindow() as Electron.BrowserWindow);

      // Verify rollback executed
      const state = await readState();
      expect(state.currentVersion).toBe('1.0.0'); // rolled back
      expect(state.crashCount).toBe(0); // reset by rollback

      // Verify .prev was restored as install dir
      await expect(fs.access(installDir)).resolves.toBeUndefined();
      await expect(fs.access(prevDir)).rejects.toThrow();

      // Verify marker file from previous version survived the rename
      const marker = await fs.readFile(path.join(installDir, 'marker.txt'), 'utf8');
      expect(marker).toBe('previous-good-version');

      // Verify app restart was requested
      const { app } = await import('electron');
      expect(vi.mocked(app.relaunch)).toHaveBeenCalled();
      expect(vi.mocked(app.exit)).toHaveBeenCalledWith(0);

      // Verify rollback event was reported to the server
      expect(fetch).toHaveBeenCalledWith(
        'https://updates.sage.app/api/v1/updates/rollbacks',
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        }),
      );
    });

    it('increments crash count without rollback when below threshold', async () => {
      // crashCount starts at 0, threshold is 3
      const stateManager = new StateManager();
      const baseState = await stateManager.getState();
      await stateManager.setState({
        ...baseState,
        crashCount: 0,
        lastRecordedVersion: baseState.currentVersion,
      });

      mockRunPostStartupChecks.mockResolvedValue({
        passed: false,
        details: [{ name: 'backend', passed: false, error: 'unhealthy' }],
      });

      // Should throw (not trigger rollback)
      await expect(
        updateManager.onAppStartup(() => createVisibleWindow() as Electron.BrowserWindow),
      ).rejects.toThrow('Health check failed (1/3)');

      const state = await readState();
      expect(state.crashCount).toBe(1);
      // No rollback: currentVersion unchanged
      expect(state.currentVersion).toBe('1.0.0');
    });
  });

  // ─────────────────────────────────────────────────────────────────────────
  // Scenario 5: Manual rollback within window
  // ─────────────────────────────────────────────────────────────────────────
  describe('Scenario 5: Manual rollback', () => {
    it('allows rollback within 7-day window', async () => {
      // Set up install directories
      const { installDir, prevDir } = useTempInstallDir();
      await fs.mkdir(installDir, { recursive: true });
      await fs.mkdir(prevDir, { recursive: true });
      await fs.writeFile(path.join(prevDir, 'marker.txt'), 'v1-content');

      // Seed state: v2.0.0 installed 3 days ago, lastKnownGood = v1.0.0
      const stateManager = new StateManager();
      const baseState = await stateManager.getState();
      await stateManager.setState({
        ...baseState,
        currentVersion: '2.0.0',
        lastKnownGoodVersion: '1.0.0',
        lastKnownGoodInstallDate: new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString(),
        crashCount: 0,
      });

      // Verify rollback is allowed
      const canRollback = await updateManager.canManualRollback();
      expect(canRollback.allowed).toBe(true);

      // Execute rollback
      await updateManager.rollback('user-requested');

      // Verify state was updated
      const state = await readState();
      expect(state.currentVersion).toBe('1.0.0');
      expect(state.crashCount).toBe(0);

      // Verify .prev restored
      await expect(fs.access(installDir)).resolves.toBeUndefined();
      await expect(fs.access(prevDir)).rejects.toThrow();

      // Verify marker file from previous version survived
      const marker = await fs.readFile(path.join(installDir, 'marker.txt'), 'utf8');
      expect(marker).toBe('v1-content');
    });

    it('rejects rollback after window expires', async () => {
      // Seed state: installed 10 days ago (window = 7 days)
      const stateManager = new StateManager();
      const baseState = await stateManager.getState();
      await stateManager.setState({
        ...baseState,
        currentVersion: '2.0.0',
        lastKnownGoodVersion: '1.0.0',
        lastKnownGoodInstallDate: new Date(Date.now() - 10 * 24 * 60 * 60 * 1000).toISOString(),
      });

      const canRollback = await updateManager.canManualRollback();
      expect(canRollback.allowed).toBe(false);
      expect(canRollback.reason).toContain('Rollback window closed');
    });

    it('rejects rollback when already on the stable version', async () => {
      const stateManager = new StateManager();
      const baseState = await stateManager.getState();
      await stateManager.setState({
        ...baseState,
        currentVersion: '1.0.0',
        lastKnownGoodVersion: '1.0.0',
      });

      const canRollback = await updateManager.canManualRollback();
      expect(canRollback.allowed).toBe(false);
      expect(canRollback.reason).toBe('Already on stable version');
    });
  });

  // ─────────────────────────────────────────────────────────────────────────
  // Scenario 6: Channel switching
  // ─────────────────────────────────────────────────────────────────────────
  describe('Scenario 6: Channel switching', () => {
    it('persists channel changes and uses them for update checks', async () => {
      // Default channel is 'stable'
      let config = await updateManager.getConfig();
      expect(config.channel).toBe('stable');

      // Switch to beta
      await updateManager.setChannel('beta');
      config = await updateManager.getConfig();
      expect(config.channel).toBe('beta');

      // Verify beta channel is used in the manifest URL
      vi.mocked(fetch).mockResolvedValue(
        createResponse(200, createManifest('2.0.0', { channel: 'beta' })),
      );

      await updateManager.checkForUpdates();

      expect(fetch).toHaveBeenCalledWith(
        'https://updates.sage.app/api/v1/updates/latest?channel=beta',
      );

      // Verify beta updater channel
      await updateManager.downloadUpdate();
      expect(updater.setFeedURL).toHaveBeenCalledWith(expect.objectContaining({ channel: 'beta' }));

      // Config persists across reads
      const savedConfig = await readConfig();
      expect(savedConfig.channel).toBe('beta');
    });

    it('switches from beta to alpha and uses alpha feed', async () => {
      await updateManager.setChannel('beta');
      await updateManager.setChannel('alpha');

      const config = await updateManager.getConfig();
      expect(config.channel).toBe('alpha');

      vi.mocked(fetch).mockResolvedValue(
        createResponse(200, createManifest('2.0.0', { channel: 'alpha' })),
      );

      await updateManager.checkForUpdates();

      expect(fetch).toHaveBeenCalledWith(
        'https://updates.sage.app/api/v1/updates/latest?channel=alpha',
      );

      await updateManager.downloadUpdate();
      expect(updater.setFeedURL).toHaveBeenCalledWith(
        expect.objectContaining({ channel: 'alpha' }),
      );
    });

    it('invalidates cached check result when channel changes', async () => {
      // First check on stable → no update
      vi.mocked(fetch).mockResolvedValue(createResponse(404, {}));
      await updateManager.checkForUpdates();

      // Switch channel — should invalidate cached result
      await updateManager.setChannel('beta');

      // downloadUpdate should fail because cache was invalidated
      await expect(updateManager.downloadUpdate()).rejects.toThrow(
        'No update is available to download',
      );
    });
  });
});
