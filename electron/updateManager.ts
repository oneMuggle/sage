import { StateManager, UpdateState } from './updateState';
import { ConfigManager, UpdateConfig } from './updateConfig';

export interface CheckResult {
  updateAvailable: boolean;
  version?: string;
  releaseNotes?: string;
  downloadUrl?: string;
}

export class UpdateManager {
  private stateManager: StateManager;
  private configManager: ConfigManager;

  constructor() {
    this.stateManager = new StateManager();
    this.configManager = new ConfigManager();
  }

  async checkForUpdates(): Promise<CheckResult> {
    const config = await this.configManager.getConfig();
    const state = await this.stateManager.getState();

    try {
      // Fetch latest manifest from server
      const response = await fetch(
        `${config.updateServerUrl}/api/v1/updates/latest?channel=${config.channel}`
      );

      if (!response.ok) {
        if (response.status === 404) {
          return { updateAvailable: false };
        }
        throw new Error(`Server returned ${response.status}`);
      }

      const manifest = await response.json();

      // Check if version is newer than current
      if (this.isNewerVersion(manifest.version, state.currentVersion)) {
        // Check if current version meets minimum upgradable version
        if (!this.meetsMinimumVersion(state.currentVersion, manifest.min_upgradable_version)) {
          console.warn(`Current version ${state.currentVersion} cannot upgrade to ${manifest.version}`);
          return { updateAvailable: false };
        }

        // Determine platform-specific file
        const platformKey = this.getPlatformKey();
        const fileMeta = manifest.files[platformKey];

        if (!fileMeta) {
          console.warn(`No update file for platform ${platformKey}`);
          return { updateAvailable: false };
        }

        // Update state with check time
        state.lastCheckTime = new Date().toISOString();
        await this.stateManager.setState(state);

        return {
          updateAvailable: true,
          version: manifest.version,
          releaseNotes: manifest.release_notes,
          downloadUrl: fileMeta.url,
        };
      }

      // No update available
      state.lastCheckTime = new Date().toISOString();
      await this.stateManager.setState(state);

      return { updateAvailable: false };
    } catch (error) {
      console.error('Failed to check for updates:', error);
      throw error;
    }
  }

  async downloadUpdate(): Promise<void> {
    // TODO: Implement in Task 5 (electron-updater integration)
    throw new Error('Not implemented');
  }

  async installUpdate(): Promise<void> {
    // TODO: Implement in Task 6 (cover upgrade coordinator)
    throw new Error('Not implemented');
  }

  private isNewerVersion(latest: string, current: string): boolean {
    const [latestMajor, latestMinor, latestPatch] = latest.split('.').map(Number);
    const [currentMajor, currentMinor, currentPatch] = current.split('.').map(Number);

    if (latestMajor !== currentMajor) return latestMajor > currentMajor;
    if (latestMinor !== currentMinor) return latestMinor > currentMinor;
    return latestPatch > currentPatch;
  }

  private meetsMinimumVersion(current: string, minimum: string): boolean {
    const [currentMajor, currentMinor, currentPatch] = current.split('.').map(Number);
    const [minMajor, minMinor, minPatch] = minimum.split('.').map(Number);

    if (currentMajor !== minMajor) return currentMajor >= minMajor;
    if (currentMinor !== minMinor) return currentMinor >= minMinor;
    return currentPatch >= minPatch;
  }

  private getPlatformKey(): string {
    const platform = process.platform;
    const arch = process.arch;

    if (platform === 'win32') {
      return arch === 'x64' ? 'win-x64' : 'win-ia32';
    } else if (platform === 'linux') {
      return 'linux-x64';
    } else if (platform === 'darwin') {
      return arch === 'arm64' ? 'mac-arm64' : 'mac-x64';
    }

    throw new Error(`Unsupported platform: ${platform}-${arch}`);
  }
}
