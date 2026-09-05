import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import * as fs from 'fs/promises';
import * as path from 'path';

// Mock Electron app
const mockUserData = '/tmp/test-user-data';
vi.mock('electron', () => ({
  app: {
    getPath: (name: string) => {
      if (name === 'userData') return mockUserData;
      throw new Error(`Unknown path: ${name}`);
    },
    getVersion: () => '1.0.0',
  },
}));

// Import AFTER vi.mock so the module sees the mocked electron
const { StateManager } = await import('../updateState');
type UpdateState = import('../updateState').UpdateState;

describe('StateManager', () => {
  let stateManager: InstanceType<typeof StateManager>;
  let statePath: string;

  beforeEach(async () => {
    await fs.mkdir(mockUserData, { recursive: true });
    stateManager = new StateManager();
    statePath = path.join(mockUserData, 'update-state.json');
  });

  afterEach(async () => {
    await fs.rm(mockUserData, { recursive: true, force: true });
  });

  it('returns default state when file does not exist', async () => {
    const state = await stateManager.getState();
    expect(state.currentVersion).toBe('1.0.0');
    expect(state.crashCount).toBe(0);
    expect(state.updateStrategy).toBe('auto-download');
  });

  it('persists and retrieves state', async () => {
    const newState: UpdateState = {
      currentVersion: '1.2.3',
      lastKnownGoodVersion: '1.2.3',
      lastKnownGoodInstallDate: '2026-09-05T12:00:00.000Z',
      crashCount: 2,
      rollbackWindowDays: 7,
      updateStrategy: 'manual',
      lastCheckTime: '2026-09-05T10:00:00.000Z',
      pendingUpdate: null,
      lastRecordedVersion: '1.2.3',
    };

    await stateManager.setState(newState);
    const retrieved = await stateManager.getState();

    expect(retrieved.currentVersion).toBe('1.2.3');
    expect(retrieved.crashCount).toBe(2);
    expect(retrieved.updateStrategy).toBe('manual');
  });

  it('includes HMAC in persisted state', async () => {
    const state = await stateManager.getState();
    await stateManager.setState(state);

    const data = await fs.readFile(statePath, 'utf-8');
    const parsed = JSON.parse(data);

    expect(parsed).toHaveProperty('hmac');
    expect(typeof parsed.hmac).toBe('string');
    expect(parsed.hmac).toHaveLength(64); // SHA-256 hex
  });

  it('returns defaults when HMAC is tampered', async () => {
    const state = await stateManager.getState();
    await stateManager.setState(state);

    // Tamper with state
    const data = await fs.readFile(statePath, 'utf-8');
    const parsed = JSON.parse(data);
    parsed.crashCount = 999; // Modify state without updating HMAC
    await fs.writeFile(statePath, JSON.stringify(parsed), 'utf-8');

    const retrieved = await stateManager.getState();
    expect(retrieved.crashCount).toBe(0); // Reset to default
  });
});
