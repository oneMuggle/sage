import { app, BrowserWindow } from 'electron';
import { autoUpdater } from 'electron-updater';
import * as fs from 'fs/promises';
import * as path from 'path';
import { StateManager } from './updateState';
import type { UpdateState } from './updateState';
import { ConfigManager } from './updateConfig';
import type { UpdateStrategy } from './updateConfig';
import { LauncherHealthChecker } from './updateHealthChecker';

export interface CheckResult {
  updateAvailable: boolean;
  version?: string;
  releaseNotes?: string;
  downloadUrl?: string;
}

interface SemVer {
  major: string;
  minor: string;
  patch: string;
  prerelease: string[];
}

interface UpdateFile {
  filename: string;
  url: string;
  sha512: string;
  size: number;
  signature: string;
}

interface UpdateManifest {
  version: string;
  min_upgradable_version: string;
  release_notes?: string;
  files: Record<string, UpdateFile>;
}

export interface UpdaterBoundary {
  setFeedURL(options: { provider: 'generic'; url: string; channel: string }): void;
  checkForUpdates(): Promise<unknown>;
  downloadUpdate(): Promise<unknown>;
  quitAndInstall(): void;
  on(event: 'download-progress', listener: (event: { percent: number }) => void): void;
  off(event: 'download-progress', listener: (event: { percent: number }) => void): void;
}

interface UpdaterCheckResult {
  updateInfo?: {
    version?: string;
    files?: Array<{
      url?: string;
      sha512?: string;
      size?: number;
    }>;
  };
}

interface CheckedUpdate {
  version: string;
  fileUrl: string;
  filename: string;
  sha512: string;
  size: number;
  channel: string;
}

const SEMVER_PATTERN =
  /^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/;

export class UpdateManager {
  private stateManager: StateManager;
  private configManager: ConfigManager;
  private updater: UpdaterBoundary;
  private lastCheckedUpdate: CheckedUpdate | null = null;

  constructor(updater: UpdaterBoundary = autoUpdater as unknown as UpdaterBoundary) {
    this.stateManager = new StateManager();
    this.configManager = new ConfigManager();
    this.updater = updater;
  }

  async checkForUpdates(): Promise<CheckResult> {
    this.lastCheckedUpdate = null;
    const config = await this.configManager.getConfig();
    const state = await this.stateManager.getState();

    try {
      // Fetch latest manifest from server
      const response = await fetch(
        `${config.updateServerUrl}/api/v1/updates/latest?channel=${config.channel}`,
      );

      if (!response.ok) {
        this.lastCheckedUpdate = null;
        if (response.status === 404) {
          state.lastCheckTime = new Date().toISOString();
          await this.stateManager.setState(state);
          return { updateAvailable: false };
        }
        throw new Error(`Server returned ${response.status}`);
      }

      const manifest = this.validateManifest(await response.json());

      // Check if version is newer than current
      if (this.isNewerVersion(manifest.version, state.currentVersion)) {
        // Check if current version meets minimum upgradable version
        if (!this.meetsMinimumVersion(state.currentVersion, manifest.min_upgradable_version)) {
          this.lastCheckedUpdate = null;
          console.warn(
            `Current version ${state.currentVersion} cannot upgrade to ${manifest.version}`,
          );
          return { updateAvailable: false };
        }

        // Determine platform-specific file
        const platformKey = this.getPlatformKey();
        const fileMeta = manifest.files[platformKey];

        if (!fileMeta) {
          this.lastCheckedUpdate = null;
          console.warn(`No update file for platform ${platformKey}`);
          return { updateAvailable: false };
        }

        // Update state with check time
        state.lastCheckTime = new Date().toISOString();
        await this.stateManager.setState(state);
        this.lastCheckedUpdate = {
          version: manifest.version,
          fileUrl: fileMeta.url,
          filename: fileMeta.filename,
          sha512: fileMeta.sha512,
          size: fileMeta.size,
          channel: config.channel,
        };

        return {
          updateAvailable: true,
          version: manifest.version,
          releaseNotes: manifest.release_notes,
          downloadUrl: fileMeta.url,
        };
      }

      // No update available
      this.lastCheckedUpdate = null;
      state.lastCheckTime = new Date().toISOString();
      await this.stateManager.setState(state);

      return { updateAvailable: false };
    } catch (error) {
      console.error('Failed to check for updates:', error);
      throw error;
    }
  }

  async downloadUpdate(): Promise<void> {
    const checkedUpdate = this.lastCheckedUpdate;
    if (!checkedUpdate) {
      throw new Error('No update is available to download');
    }

    try {
      const feedUrl = this.getFeedUrl(checkedUpdate.fileUrl);
      this.updater.setFeedURL({
        provider: 'generic',
        url: feedUrl,
        channel: this.getUpdaterChannel(checkedUpdate.channel),
      });
      const updaterResult = (await this.updater.checkForUpdates()) as UpdaterCheckResult | null;
      const updaterVersion = updaterResult?.updateInfo?.version;
      if (!updaterVersion || updaterVersion !== checkedUpdate.version) {
        throw new Error('Updater metadata does not match the checked update');
      }
      const updaterFile = updaterResult?.updateInfo?.files?.find(
        (file) => this.getArtifactBasename(file.url, feedUrl) === checkedUpdate.filename,
      );
      if (
        !updaterFile ||
        updaterFile.sha512 !== checkedUpdate.sha512 ||
        updaterFile.size !== checkedUpdate.size
      ) {
        throw new Error('Updater metadata does not match the checked update');
      }
      await this.updater.downloadUpdate();

      const state = await this.stateManager.getState();
      await this.stateManager.setState({
        ...state,
        pendingUpdate: {
          version: checkedUpdate.version,
          downloadedAt: new Date().toISOString(),
        },
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      throw new Error(`Failed to download update: ${message}`);
    }
  }

  onDownloadProgress(callback: (percent: number) => void): () => void {
    const listener = (event: { percent: number }) => callback(event.percent);
    this.updater.on('download-progress', listener);
    return () => this.updater.off('download-progress', listener);
  }

  async setStrategy(strategy: UpdateStrategy): Promise<void> {
    // TODO (Task 10): read-modify-write is non-atomic; concurrent calls may
    // cause lost updates. Add mutex or atomic rename in ConfigManager.
    const config = await this.configManager.getConfig();
    await this.configManager.setConfig({ ...config, updateStrategy: strategy });
  }

  private getFeedUrl(fileUrl: string): string {
    const url = new URL(fileUrl);
    const directoryPath = url.pathname.slice(0, url.pathname.lastIndexOf('/') + 1);
    return `${url.origin}${directoryPath}`;
  }

  private getUpdaterChannel(channel: string): string {
    return channel === 'stable' ? 'latest' : channel;
  }

  private getArtifactBasename(fileUrl: string | undefined, baseUrl: string): string | null {
    if (!fileUrl) return null;
    try {
      const pathname = new URL(fileUrl, baseUrl).pathname;
      const basename = pathname.slice(pathname.lastIndexOf('/') + 1);
      return decodeURIComponent(basename);
    } catch {
      return null;
    }
  }

  async installUpdate(): Promise<void> {
    const state = await this.stateManager.getState();

    if (!state.pendingUpdate) {
      throw new Error('No pending update to install');
    }

    await this.prepareForUpgrade();

    this.updater.quitAndInstall();

    // If we reach here, quitAndInstall() hasn't exited the process yet.
    await this.stateManager.setState({
      ...state,
      currentVersion: state.pendingUpdate.version,
      lastKnownGoodVersion: state.currentVersion,
      lastKnownGoodInstallDate: new Date().toISOString(),
      crashCount: 0,
      pendingUpdate: null,
    });
  }

  async onAppStartup(getWindow: () => BrowserWindow | null): Promise<void> {
    const state = await this.stateManager.getState();

    // Reset crash count if version changed since last recording
    if (state.currentVersion !== state.lastRecordedVersion) {
      state.crashCount = 0;
      state.lastRecordedVersion = state.currentVersion;
      await this.stateManager.setState(state);
    }

    // Run post-startup health checks
    const healthChecker = new LauncherHealthChecker({ getWindow });
    const health = await healthChecker.runPostStartupChecks();

    if (!health.passed) {
      state.crashCount += 1;
      await this.stateManager.setState(state);

      const config = await this.configManager.getConfig();
      if (state.crashCount >= config.autoRollbackThreshold) {
        await this.rollback('auto-rollback:health-check-failed');
        return; // rollback() calls app.exit(), but TypeScript needs this
      }

      throw new Error(`Health check failed (${state.crashCount}/${config.autoRollbackThreshold})`);
    }

    // Health checks passed: reset crash count if it was non-zero
    if (state.crashCount > 0) {
      state.crashCount = 0;
      await this.stateManager.setState(state);
    }
  }

  async rollback(reason: string): Promise<void> {
    const state = await this.stateManager.getState();

    // 1. Report rollback event (non-blocking)
    await this.reportRollbackEvent(reason, state);

    // 2. Check if .prev exists
    const installDir = path.dirname(process.execPath);
    const prevDir = path.join(path.dirname(installDir), '.prev');

    if (!(await this.pathExists(prevDir))) {
      // No .prev, try reinstalling from cached package
      await this.reinstallFromPackage(state, installDir);
      return;
    }

    // 3. Delete current install dir
    await fs.rm(installDir, { recursive: true, force: true });

    // 4. Restore .prev as install dir
    await fs.rename(prevDir, installDir);

    // 5. Update state
    await this.stateManager.setState({
      ...state,
      currentVersion: state.lastKnownGoodVersion,
      crashCount: 0,
    });

    // 6. Restart app
    app.relaunch();
    app.exit(0);
  }

  async canManualRollback(): Promise<{ allowed: boolean; reason?: string }> {
    const state = await this.stateManager.getState();

    if (!state.lastKnownGoodVersion) {
      return { allowed: false, reason: 'No known stable version available' };
    }

    if (state.currentVersion === state.lastKnownGoodVersion) {
      return { allowed: false, reason: 'Already on stable version' };
    }

    const config = await this.configManager.getConfig();
    const installDate = state.lastKnownGoodInstallDate
      ? new Date(state.lastKnownGoodInstallDate)
      : null;

    if (!installDate) {
      return { allowed: false, reason: 'Rollback window unknown' };
    }

    const daysSinceInstall = (Date.now() - installDate.getTime()) / (1000 * 60 * 60 * 24);

    if (daysSinceInstall > config.rollbackWindowDays) {
      return {
        allowed: false,
        reason: `Rollback window closed (${config.rollbackWindowDays} days)`,
      };
    }

    return { allowed: true };
  }

  private async reportRollbackEvent(reason: string, state: UpdateState): Promise<void> {
    try {
      const config = await this.configManager.getConfig();
      await fetch(`${config.updateServerUrl}/api/v1/updates/rollbacks`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          from_version: state.currentVersion,
          to_version: state.lastKnownGoodVersion,
          reason,
          crash_count: state.crashCount,
          timestamp: new Date().toISOString(),
        }),
      });
    } catch {
      // Non-blocking: ignore reporting failures
    }
  }

  private async reinstallFromPackage(state: UpdateState, installDir: string): Promise<void> {
    const cacheDir = path.join(app.getPath('userData'), 'updates', 'cache');
    const packagePath = path.join(cacheDir, `Sage-Setup-${state.lastKnownGoodVersion}.exe`);

    if (!(await this.pathExists(packagePath))) {
      throw new Error('No rollback package available');
    }

    const { spawn } = await import('child_process');
    const installer = spawn(packagePath, ['/S', `/D=${installDir}`]);

    await new Promise<void>((resolve, reject) => {
      installer.on('exit', (code: number) => {
        if (code === 0) {
          resolve();
        } else {
          reject(new Error(`Installer exited with code ${code}`));
        }
      });
    });

    // Restart app after reinstall
    app.relaunch();
    app.exit(0);
  }

  private async pathExists(p: string): Promise<boolean> {
    try {
      await fs.access(p);
      return true;
    } catch {
      return false;
    }
  }

  private async prepareForUpgrade(): Promise<void> {
    const installDir = path.dirname(process.execPath);
    const prevDir = path.join(path.dirname(installDir), '.prev');

    // Clean up stale .prev from a prior upgrade
    try {
      await fs.rm(prevDir, { recursive: true, force: true });
    } catch {
      // Ignore if absent or not removable
    }

    if (process.platform === 'win32') {
      // Windows locks the running executable's directory, so defer the rename
      // to a post-exit batch script that the installer can invoke.
      const scriptPath = path.join(path.dirname(installDir), '.prepare-rollback.bat');
      const script = [
        '@echo off',
        'timeout /t 2 /nobreak >nul',
        `move /y "${installDir}" "${prevDir}"`,
        'del "%~f0"',
        '',
      ].join('\r\n');
      await fs.writeFile(scriptPath, script, { mode: 0o755 });
    } else {
      // On Linux/macOS, rename the install directory directly.
      await fs.rename(installDir, prevDir);
    }
  }

  private isNewerVersion(latest: string, current: string): boolean {
    return (
      this.compareVersions(
        this.parseVersion(latest, 'latest'),
        this.parseVersion(current, 'currentVersion'),
      ) > 0
    );
  }

  private meetsMinimumVersion(current: string, minimum: string): boolean {
    return (
      this.compareVersions(
        this.parseVersion(current, 'currentVersion'),
        this.parseVersion(minimum, 'minimum'),
      ) >= 0
    );
  }

  private getPlatformKey(): string {
    const platform = process.platform;
    const arch = process.arch;

    if (platform === 'win32') {
      if (arch === 'x64') return 'win-x64';
      if (arch === 'ia32') return 'win-ia32';
      throw new Error(`Unsupported platform: ${platform}-${arch}`);
    } else if (platform === 'linux') {
      if (arch === 'x64') return 'linux-x64';
      throw new Error(`Unsupported platform: ${platform}-${arch}`);
    } else if (platform === 'darwin') {
      if (arch === 'x64') return 'mac-x64';
      if (arch === 'arm64') return 'mac-arm64';
      throw new Error(`Unsupported platform: ${platform}-${arch}`);
    }

    throw new Error(`Unsupported platform: ${platform}-${arch}`);
  }

  private parseVersion(version: string, field: string): SemVer {
    const match = SEMVER_PATTERN.exec(version);
    if (!match) throw new Error(`Invalid ${field}: ${JSON.stringify(version)}`);
    const prerelease = (match[4] ?? '')
      .split('.')
      .filter(Boolean)
      .map((identifier) => {
        if (/^\d+$/.test(identifier)) {
          if (identifier.length > 1 && identifier.startsWith('0')) {
            throw new Error(`Invalid ${field}: ${JSON.stringify(version)}`);
          }
          return identifier;
        }
        return identifier;
      });
    return {
      major: match[1],
      minor: match[2],
      patch: match[3],
      prerelease,
    };
  }

  private compareVersions(left: SemVer, right: SemVer): number {
    for (const field of ['major', 'minor', 'patch'] as const) {
      const comparison = this.compareNumericIdentifiers(left[field], right[field]);
      if (comparison !== 0) return comparison;
    }
    if (left.prerelease.length === 0 && right.prerelease.length === 0) return 0;
    if (left.prerelease.length === 0) return 1;
    if (right.prerelease.length === 0) return -1;
    const length = Math.max(left.prerelease.length, right.prerelease.length);
    for (let index = 0; index < length; index += 1) {
      const leftIdentifier = left.prerelease[index];
      const rightIdentifier = right.prerelease[index];
      if (leftIdentifier === undefined) return -1;
      if (rightIdentifier === undefined) return 1;
      if (leftIdentifier === rightIdentifier) continue;
      const leftIsNumeric = /^\d+$/.test(leftIdentifier);
      const rightIsNumeric = /^\d+$/.test(rightIdentifier);
      if (leftIsNumeric && !rightIsNumeric) return -1;
      if (!leftIsNumeric && rightIsNumeric) return 1;
      if (leftIsNumeric && rightIsNumeric) {
        const comparison = this.compareNumericIdentifiers(leftIdentifier, rightIdentifier);
        if (comparison !== 0) return comparison;
      } else {
        return leftIdentifier > rightIdentifier ? 1 : -1;
      }
    }
    return 0;
  }

  private compareNumericIdentifiers(left: string, right: string): number {
    const normalizedLeft = left.replace(/^0+(?=\d)/, '');
    const normalizedRight = right.replace(/^0+(?=\d)/, '');
    if (normalizedLeft.length !== normalizedRight.length) {
      return normalizedLeft.length > normalizedRight.length ? 1 : -1;
    }
    if (normalizedLeft === normalizedRight) return 0;
    return normalizedLeft > normalizedRight ? 1 : -1;
  }

  private validateManifest(value: unknown): UpdateManifest {
    if (!this.isRecord(value)) throw new Error('Invalid update manifest: expected an object');
    if (typeof value.version !== 'string') throw new Error('Invalid update manifest.version');
    if (typeof value.min_upgradable_version !== 'string') {
      throw new Error('Invalid update manifest.min_upgradable_version');
    }
    this.parseVersion(value.version, 'manifest.version');
    this.parseVersion(value.min_upgradable_version, 'manifest.min_upgradable_version');
    if (value.release_notes !== undefined && typeof value.release_notes !== 'string') {
      throw new Error('Invalid update manifest.release_notes');
    }
    if (!this.isRecord(value.files)) throw new Error('Invalid update manifest.files');
    const platformKey = this.getPlatformKey();
    const file = value.files[platformKey];
    if (!this.isRecord(file)) throw new Error(`Invalid update manifest.files.${platformKey}`);
    if (typeof file.filename !== 'string' || file.filename.length === 0) {
      throw new Error(`Invalid update manifest.files.${platformKey}.filename`);
    }
    if (typeof file.url !== 'string' || !this.isHttpUrl(file.url)) {
      throw new Error(`Invalid update manifest.files.${platformKey}.url`);
    }
    if (typeof file.sha512 !== 'string' || !/^[a-fA-F0-9]{128}$/.test(file.sha512)) {
      throw new Error(`Invalid update manifest.files.${platformKey}.sha512`);
    }
    if (typeof file.size !== 'number' || !Number.isSafeInteger(file.size) || file.size <= 0) {
      throw new Error(`Invalid update manifest.files.${platformKey}.size`);
    }
    if (typeof file.signature !== 'string' || file.signature.length === 0) {
      throw new Error(`Invalid update manifest.files.${platformKey}.signature`);
    }
    return {
      version: value.version,
      min_upgradable_version: value.min_upgradable_version,
      release_notes: typeof value.release_notes === 'string' ? value.release_notes : undefined,
      files: {
        [platformKey]: {
          filename: file.filename,
          url: file.url,
          sha512: file.sha512,
          size: file.size,
          signature: file.signature,
        },
      },
    };
  }

  private isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
  }

  private isHttpUrl(value: string): boolean {
    try {
      const protocol = new URL(value).protocol;
      return protocol === 'http:' || protocol === 'https:';
    } catch {
      return false;
    }
  }
}
