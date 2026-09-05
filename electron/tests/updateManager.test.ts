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

function createResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

function createManifest(
  version: string,
  options: { minimum?: string; includePlatformFile?: boolean } = {},
): Record<string, unknown> {
  return {
    version,
    channel: 'stable',
    release_date: '2026-09-05T12:00:00Z',
    release_notes: '## New features',
    min_upgradable_version: options.minimum ?? '1.0.0',
    files: options.includePlatformFile === false
      ? {}
      : {
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

  it('records last check time when server returns 404', async () => {
    vi.mocked(fetch).mockResolvedValue(createResponse(404, {}));

    await updateManager.checkForUpdates();

    const state = JSON.parse(await fs.readFile(`${mockUserData}/update-state.json`, 'utf8'));
    expect(state.lastCheckTime).toEqual(expect.any(String));
  });

  it('rejects an update when current version is below minimum', async () => {
    vi.mocked(fetch).mockResolvedValue(
      createResponse(200, createManifest('1.3.0', { minimum: '1.1.0' })),
    );

    const result = await updateManager.checkForUpdates();

    expect(result.updateAvailable).toBe(false);
  });

  it('compares prerelease versions according to semver ordering', () => {
    const compareVersions = (updateManager as unknown as {
      compareVersions: (left: unknown, right: unknown) => number;
    }).compareVersions;
    const parseVersion = (updateManager as unknown as {
      parseVersion: (version: string, field: string) => unknown;
    }).parseVersion;

    expect(compareVersions(parseVersion('1.0.0-beta.2', 'test'), parseVersion('1.0.0-beta.11', 'test')))
      .toBeLessThan(0);
    expect(compareVersions(parseVersion('1.0.0', 'test'), parseVersion('1.0.0-rc.1', 'test')))
      .toBeGreaterThan(0);
  });

  it('throws a diagnostic error for an invalid manifest', async () => {
    vi.mocked(fetch).mockResolvedValue(createResponse(200, { version: 'not-a-version' }));

    await expect(updateManager.checkForUpdates()).rejects.toThrow('min_upgradable_version');
  });

  it('throws when the platform file is missing', async () => {
    vi.mocked(fetch).mockResolvedValue(
      createResponse(200, createManifest('1.3.0', { includePlatformFile: false })),
    );

    await expect(updateManager.checkForUpdates()).rejects.toThrow(`files.${platformKey}`);
  });

  it('rejects invalid download URLs', async () => {
    const manifest = createManifest('1.3.0');
    (manifest.files as Record<string, Record<string, string>>)[platformKey].url = 'not-a-url';
    vi.mocked(fetch).mockResolvedValue(createResponse(200, manifest));

    await expect(updateManager.checkForUpdates()).rejects.toThrow(`files.${platformKey}.url`);
  });

  it('rejects incomplete file metadata', async () => {
    const manifest = createManifest('1.3.0');
    delete (manifest.files as Record<string, Record<string, unknown>>)[platformKey].sha512;
    vi.mocked(fetch).mockResolvedValue(createResponse(200, manifest));

    await expect(updateManager.checkForUpdates()).rejects.toThrow(`files.${platformKey}.sha512`);
  });

  it('rejects unsupported host architectures instead of selecting another platform file', async () => {
    const originalArch = process.arch;
    Object.defineProperty(process, 'arch', { value: 'arm64', configurable: true });
    try {
      expect(() => (updateManager as unknown as { getPlatformKey: () => string }).getPlatformKey())
        .toThrow(`Unsupported platform: ${process.platform}-arm64`);
    } finally {
      Object.defineProperty(process, 'arch', { value: originalArch, configurable: true });
    }
  });

  it('throws error when server returns 500', async () => {
    vi.mocked(fetch).mockResolvedValue(createResponse(500, {}));

    await expect(updateManager.checkForUpdates()).rejects.toThrow('Server returned 500');
  });
});
