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
  },
}));

const { UpdateManager } = await import('../updateManager');

const platformKey = process.platform === 'linux'
  ? 'linux-x64'
  : process.platform === 'darwin'
    ? (process.arch === 'arm64' ? 'mac-arm64' : 'mac-x64')
    : (process.arch === 'x64' ? 'win-x64' : 'win-ia32');

function createResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

function createManifest(version: string): Record<string, unknown> {
  return {
    version,
    channel: 'stable',
    release_date: '2026-09-05T12:00:00Z',
    release_notes: '## New features',
    min_upgradable_version: '1.0.0',
    files: {
      [platformKey]: {
        filename: `Sage-Setup-${version}.bin`,
        url: `https://updates.sage.app/Sage-Setup-${version}.bin`,
        sha512: 'a'.repeat(128),
        size: 104857600,
        signature: 'sig',
      },
    },
    components: {},
  };
}

describe('UpdateManager', () => {
  let updateManager: InstanceType<typeof UpdateManager>;

  beforeEach(async () => {
    await fs.mkdir(mockUserData, { recursive: true });
    await fs.rm(`${mockUserData}/update-state.json`, { force: true });
    await fs.rm(`${mockUserData}/update-config.json`, { force: true });
    updateManager = new UpdateManager();
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
    expect(result.downloadUrl).toBe('https://updates.sage.app/Sage-Setup-1.3.0.bin');
  });

  it('returns updateAvailable: false when current version is up to date', async () => {
    vi.mocked(fetch).mockResolvedValue(createResponse(200, createManifest('1.0.0')));

    const result = await updateManager.checkForUpdates();

    expect(result.updateAvailable).toBe(false);
  });

  it('throws error when server returns 500', async () => {
    vi.mocked(fetch).mockResolvedValue(createResponse(500, {}));

    await expect(updateManager.checkForUpdates()).rejects.toThrow('Server returned 500');
  });
});
