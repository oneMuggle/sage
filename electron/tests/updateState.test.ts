// @vitest-environment node
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import * as fs from 'fs/promises';
import * as path from 'path';
import * as fssync from 'fs';

// Mock Electron app. The mock supports ``isPackaged`` so we can simulate the
// packaged-build path without spinning up an Electron renderer.
const mockUserData = '/tmp/test-user-data';
let mockIsPackaged = false;
vi.mock('electron', () => ({
  app: {
    getPath: (name: string) => {
      if (name === 'userData') return mockUserData;
      throw new Error(`Unknown path: ${name}`);
    },
    getVersion: () => '1.0.0',
    get isPackaged() {
      return mockIsPackaged;
    },
  },
}));

// Import AFTER vi.mock so the module sees the mocked electron
const { StateManager, getUpdateHmacSecret } = await import('../updateState');
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
    delete process.env.SAGE_UPDATE_STATE_HMAC_SECRET;
    mockIsPackaged = false;
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

  it('returns defaults when a signed state has an invalid schema', async () => {
    const state = await stateManager.getState();
    await stateManager.setState(state);

    const data = JSON.parse(await fs.readFile(statePath, 'utf-8')) as Record<string, unknown>;
    data.crashCount = 'not-a-number';
    await fs.writeFile(statePath, JSON.stringify(data), 'utf-8');

    const retrieved = await stateManager.getState();
    expect(retrieved.crashCount).toBe(0);
    expect(retrieved.currentVersion).toBe('1.0.0');
  });
});

// Regression tests for ``getUpdateHmacSecret``.
//
// Bug context: alpha.18-win7 / alpha.19-win7 / alpha.37-main all crashed on
// first launch with "SAGE_UPDATE_STATE_HMAC_SECRET must be configured in
// packaged builds" because neither release.yml nor release-win7.yml ever
// injected the env var. The fix removes the ``app.isPackaged`` throw so
// packaged builds fall through to the same per-installation persistent
// secret used in dev mode.
describe('getUpdateHmacSecret', () => {
  afterEach(async () => {
    await fs.rm(mockUserData, { recursive: true, force: true });
    delete process.env.SAGE_UPDATE_STATE_HMAC_SECRET;
    mockIsPackaged = false;
  });

  it('returns the env-var secret verbatim when SAGE_UPDATE_STATE_HMAC_SECRET is set (dev)', () => {
    process.env.SAGE_UPDATE_STATE_HMAC_SECRET = 'env-var-secret-1234567890';
    expect(getUpdateHmacSecret()).toBe('env-var-secret-1234567890');
  });

  it('returns the env-var secret verbatim when SAGE_UPDATE_STATE_HMAC_SECRET is set (packaged)', () => {
    mockIsPackaged = true;
    process.env.SAGE_UPDATE_STATE_HMAC_SECRET = 'env-var-secret-packaged-abcdef';
    expect(getUpdateHmacSecret()).toBe('env-var-secret-packaged-abcdef');
  });

  it('generates a 64-char hex secret and persists it on first dev-mode launch', async () => {
    await fs.mkdir(mockUserData, { recursive: true });
    const secret = getUpdateHmacSecret();
    expect(secret).toMatch(/^[0-9a-f]{64}$/);
    const persisted = await fs.readFile(
      path.join(mockUserData, '.update-state-hmac-secret'),
      'utf-8',
    );
    expect(persisted.trim()).toBe(secret);
  });

  it('generates a 64-char hex secret on first packaged-mode launch (does NOT throw)', async () => {
    // Regression for the alpha.18/19/37 crash: previously this branch
    // threw "must be configured in packaged builds". The HMAC is local
    // integrity only — per-install random secrets are equivalent to a
    // build-time shared secret.
    mockIsPackaged = true;
    await fs.mkdir(mockUserData, { recursive: true });
    expect(() => getUpdateHmacSecret()).not.toThrow();
    const secret = getUpdateHmacSecret();
    expect(secret).toMatch(/^[0-9a-f]{64}$/);
    const persisted = await fs.readFile(
      path.join(mockUserData, '.update-state-hmac-secret'),
      'utf-8',
    );
    expect(persisted.trim()).toBe(secret);
  });

  it('returns the SAME persisted secret on subsequent calls (packaged)', async () => {
    mockIsPackaged = true;
    await fs.mkdir(mockUserData, { recursive: true });
    const first = getUpdateHmacSecret();
    // Pre-seed the env var to "" so we exercise the persisted-path branch
    // even if a previous test left state behind.
    delete process.env.SAGE_UPDATE_STATE_HMAC_SECRET;
    const second = getUpdateHmacSecret();
    expect(second).toBe(first);
    // Third call from a fresh StateManager — same secret, no regeneration.
    const third = new StateManager()['hmacSecret' as keyof StateManager] as unknown as string;
    expect(third).toBe(first);
  });

  it('persisted file is created with mode 0o600 on POSIX (best-effort)', async () => {
    if (process.platform === 'win32') return; // mode flag is POSIX-only
    await fs.mkdir(mockUserData, { recursive: true });
    getUpdateHmacSecret();
    const stat = fssync.statSync(path.join(mockUserData, '.update-state-hmac-secret'));
    // Mask permission bits — 0o600 means owner read+write, no group/other.
    expect(stat.mode & 0o777).toBe(0o600);
  });
});
