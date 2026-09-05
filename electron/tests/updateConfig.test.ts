import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import * as fs from 'fs/promises';
import * as path from 'path';

// Mock Electron app
const mockUserData = '/tmp/test-user-data-config';
vi.mock('electron', () => ({
  app: {
    getPath: (name: string) => {
      if (name === 'userData') return mockUserData;
      throw new Error(`Unknown path: ${name}`);
    },
  },
}));

// Import AFTER vi.mock so the module sees the mocked electron
const { ConfigManager } = await import('../updateConfig');
type UpdateConfig = import('../updateConfig').UpdateConfig;

describe('ConfigManager', () => {
  let configManager: InstanceType<typeof ConfigManager>;
  let configPath: string;

  beforeEach(async () => {
    await fs.mkdir(mockUserData, { recursive: true });
    configManager = new ConfigManager();
    configPath = path.join(mockUserData, 'update-config.json');
  });

  afterEach(async () => {
    await fs.rm(mockUserData, { recursive: true, force: true });
  });

  it('returns default config when file does not exist', async () => {
    const config = await configManager.getConfig();
    expect(config.updateStrategy).toBe('auto-download');
    expect(config.channel).toBe('stable');
    expect(config.rollbackWindowDays).toBe(7);
    expect(config.autoRollbackThreshold).toBe(3);
  });

  it('persists and retrieves config', async () => {
    const newConfig: UpdateConfig = {
      updateStrategy: 'manual',
      channel: 'beta',
      rollbackWindowDays: 14,
      autoRollbackThreshold: 5,
      checkIntervalHours: 12,
      updateServerUrl: 'https://custom-updates.example.com',
      enableTelemetry: true,
      cacheRetentionDays: 60,
    };

    await configManager.setConfig(newConfig);
    const retrieved = await configManager.getConfig();

    expect(retrieved.updateStrategy).toBe('manual');
    expect(retrieved.channel).toBe('beta');
    expect(retrieved.rollbackWindowDays).toBe(14);
  });
});
