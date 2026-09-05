import { autoUpdater } from 'electron-updater';
import { StateManager } from './updateState';
import { ConfigManager } from './updateConfig';

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

interface CheckedUpdate {
  version: string;
  fileUrl: string;
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
        channel: checkedUpdate.channel,
      });
      await this.updater.checkForUpdates();
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

  private getFeedUrl(fileUrl: string): string {
    const url = new URL(fileUrl);
    const directoryPath = url.pathname.slice(0, url.pathname.lastIndexOf('/') + 1);
    return `${url.origin}${directoryPath}`;
  }

  async installUpdate(): Promise<void> {
    // TODO: Implement in Task 6 (cover upgrade coordinator)
    throw new Error('Not implemented');
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
      release_notes: value.release_notes,
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
