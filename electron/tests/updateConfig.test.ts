// @vitest-environment node
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

  beforeEach(async () => {
    await fs.mkdir(mockUserData, { recursive: true });
    configManager = new ConfigManager();
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

    expect(retrieved).toEqual(newConfig);
  });

  it('falls back to defaults when a persisted config is tampered', async () => {
    const config = await configManager.getConfig();
    await configManager.setConfig(config);
    const configPath = path.join(mockUserData, 'update-config.json');
    const persisted = JSON.parse(await fs.readFile(configPath, 'utf8')) as Record<string, unknown>;
    persisted.updateServerUrl = 'https://attacker.example.test';
    await fs.writeFile(configPath, JSON.stringify(persisted), 'utf8');

    const recovered = await configManager.getConfig();
    expect(recovered.updateServerUrl).toBe('https://updates.sage.app');
  });
});
