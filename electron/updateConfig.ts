import { app } from 'electron';
import * as fs from 'fs/promises';
import * as path from 'path';

export type UpdateStrategy = 'manual' | 'auto-download' | 'auto-install';
export type UpdateChannel = 'stable' | 'beta' | 'alpha';

export interface UpdateConfig {
  updateStrategy: UpdateStrategy;
  channel: UpdateChannel;
  rollbackWindowDays: number;
  autoRollbackThreshold: number;
  checkIntervalHours: number;
  updateServerUrl: string;
  enableTelemetry: boolean;
  cacheRetentionDays: number;
}

const CONFIG_FILE = 'update-config.json';
const DEFAULT_CONFIG_URL = 'https://updates.sage.app';

export class ConfigManager {
  private configPath: string;

  constructor() {
    this.configPath = path.join(app.getPath('userData'), CONFIG_FILE);
  }

  async getConfig(): Promise<UpdateConfig> {
    try {
      const data = await fs.readFile(this.configPath, 'utf-8');
      return JSON.parse(data) as UpdateConfig;
    } catch {
      // File doesn't exist or is corrupted, return defaults
      return this.getDefaultConfig();
    }
  }

  async setConfig(config: UpdateConfig): Promise<void> {
    await fs.writeFile(this.configPath, JSON.stringify(config, null, 2), 'utf-8');
  }

  private getDefaultConfig(): UpdateConfig {
    return {
      updateStrategy: 'auto-download',
      channel: 'stable',
      rollbackWindowDays: 7,
      autoRollbackThreshold: 3,
      checkIntervalHours: 24,
      updateServerUrl: DEFAULT_CONFIG_URL,
      enableTelemetry: false,
      cacheRetentionDays: 30,
    };
  }
}
