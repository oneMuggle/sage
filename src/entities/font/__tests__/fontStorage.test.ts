import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../shared/api/settingsClient', () => ({
  settingsClient: { getPreference: vi.fn(), setPreference: vi.fn(), setPreferenceStrict: vi.fn() },
}));
import { settingsClient } from '../../../shared/api/settingsClient';
import {
  CODE_FONT_OPTIONS,
  FONT_DEFAULTS,
  normalizeFontSettings,
  normalizeFontSize,
  UI_FONT_OPTIONS,
} from '../fontOptions';
import { FONT_STORAGE_KEY, loadFontSettings, saveFontSettings } from '../fontStorage';

const defaults = { fontUi: 'inter', fontCode: 'jetbrains-mono', fontSizeUi: 14, fontSizeCode: 13 };
const local = { fontUi: 'inter', fontCode: 'consolas', fontSizeUi: 18, fontSizeCode: 16 };

beforeEach(() => {
  vi.resetAllMocks();
  localStorage.clear();
  vi.mocked(settingsClient.getPreference).mockResolvedValue(null);
  vi.mocked(settingsClient.setPreferenceStrict).mockResolvedValue(undefined);
});
afterEach(() => vi.restoreAllMocks());

describe('font definitions and normalization', () => {
  it('defaults are valid without stored preferences', () => {
    expect(FONT_DEFAULTS).toEqual(defaults);
    expect(normalizeFontSettings(undefined)).toEqual(defaults);
  });
  it('offers the approved UI and code font IDs with labels and fallback stacks', () => {
    expect(UI_FONT_OPTIONS.map((option) => option.id)).toEqual([
      'inter',
      'system',
      'noto-sans-sc',
      'pingfang',
    ]);
    expect(CODE_FONT_OPTIONS.map((option) => option.id)).toEqual([
      'jetbrains-mono',
      'fira-code',
      'source-code-pro',
      'consolas',
      'monaco',
    ]);
    for (const option of [...UI_FONT_OPTIONS, ...CODE_FONT_OPTIONS]) {
      expect(option.label).not.toBe('');
      expect(option.stack).toMatch(/(?:sans-serif|monospace)$/);
      const field = UI_FONT_OPTIONS.some((ui) => ui.id === option.id) ? 'fontUi' : 'fontCode';
      expect(normalizeFontSettings({ [field]: option.id })[field]).toBe(option.id);
    }
  });
  it('includes Noto Sans SC in the Inter fallback stack', () => {
    expect(UI_FONT_OPTIONS.find((option) => option.id === 'inter')?.stack).toContain(
      '"Noto Sans SC"',
    );
  });
  it.each([
    [9, 10],
    [10, 10],
    [24, 24],
    [25, 24],
    [16.9, 16],
    ['18.7', 18],
    [undefined, 14],
    [null, 14],
    ['', 14],
    ['  ', 14],
    ['bad', 14],
    ['14px', 14],
    [Infinity, 14],
    [NaN, 14],
    [true, 14],
    [[], 14],
  ])('normalizes size %j to %j', (input, expected) => {
    expect(normalizeFontSize(input, 14)).toBe(expected);
  });
  it('uses field defaults for invalid IDs and sizes', () => {
    expect(
      normalizeFontSettings({
        fontUi: 'consolas',
        fontCode: 'inter',
        fontSizeUi: 'oops',
        fontSizeCode: null,
      }),
    ).toEqual(defaults);
    expect(normalizeFontSettings({ fontUi: 'url(evil)', fontCode: 'unknown' })).toEqual(defaults);
  });
  it.each([null, [], 'bad', 42])('rejects malformed settings %j', (value) => {
    expect(normalizeFontSettings(value)).toEqual(defaults);
  });
});

describe('font storage', () => {
  it('caches newer edits immediately while remote writes wait and never clears newer pending state', async () => {
    let finishFirst!: () => void;
    const first = new Promise<void>((resolve) => {
      finishFirst = resolve;
    });
    let finishSecond!: () => void;
    const second = new Promise<void>((resolve) => {
      finishSecond = resolve;
    });
    let calls = 0;
    vi.mocked(settingsClient.setPreferenceStrict).mockImplementation(() =>
      ++calls <= 4 ? first : second,
    );
    const savingFirst = saveFontSettings(local);
    await Promise.resolve();
    const latest = { ...local, fontSizeUi: 24 };
    const savingSecond = saveFontSettings(latest);
    expect(JSON.parse(localStorage.getItem(FONT_STORAGE_KEY)!)).toEqual({
      ...latest,
      pending: true,
    });
    finishFirst();
    await savingFirst;
    expect(JSON.parse(localStorage.getItem(FONT_STORAGE_KEY)!)).toEqual({
      ...latest,
      pending: true,
    });
    finishSecond();
    await savingSecond;
    expect(JSON.parse(localStorage.getItem(FONT_STORAGE_KEY)!)).toEqual(latest);
    expect(await loadFontSettings()).toEqual(latest);
  });
  it('keeps the complete pending local settings after partial write failure and retries on load', async () => {
    vi.mocked(settingsClient.setPreferenceStrict).mockImplementation(async (key) => {
      if (key === 'font_code') throw new Error('offline');
    });
    await expect(saveFontSettings(local)).rejects.toThrow('offline');
    expect(JSON.parse(localStorage.getItem(FONT_STORAGE_KEY)!).pending).toBe(true);
    // Simulate a restart: a fresh module must recover the pending state from disk.
    vi.resetModules();
    const { loadFontSettings: reload } = await import('../fontStorage');
    vi.mocked(settingsClient.getPreference).mockResolvedValue('old-remote-value');
    expect(await reload()).toEqual(local);
    expect(JSON.parse(localStorage.getItem(FONT_STORAGE_KEY)!).pending).toBe(true);
    vi.mocked(settingsClient.setPreferenceStrict).mockResolvedValue(undefined);
    expect(await reload()).toEqual(local);
    expect(JSON.parse(localStorage.getItem(FONT_STORAGE_KEY)!)).toEqual(local);
    expect(settingsClient.setPreferenceStrict).toHaveBeenCalledWith('font_code', 'consolas', 'ui');
    expect(settingsClient.setPreferenceStrict).toHaveBeenCalledWith('font_size_ui', '18', 'ui');
  });
  it('loads remote first and caches only normalized values', async () => {
    localStorage.setItem(FONT_STORAGE_KEY, JSON.stringify(local));
    const remote: Record<string, string> = {
      font_ui: 'noto-sans-sc',
      font_code: 'consolas',
      font_size_ui: '30',
      font_size_code: '15.9',
    };
    vi.mocked(settingsClient.getPreference).mockImplementation(async (key) => remote[key] ?? null);
    const expected = {
      fontUi: 'noto-sans-sc',
      fontCode: 'consolas',
      fontSizeUi: 24,
      fontSizeCode: 15,
    };
    expect(await loadFontSettings()).toEqual(expected);
    expect(JSON.parse(localStorage.getItem('sage-font-settings')!)).toEqual(expected);
  });
  it('falls back per missing remote field to local cache', async () => {
    localStorage.setItem(FONT_STORAGE_KEY, JSON.stringify(local));
    vi.mocked(settingsClient.getPreference).mockImplementation(async (key) =>
      key === 'font_size_ui' ? '20' : null,
    );
    expect(await loadFontSettings()).toEqual({ ...local, fontSizeUi: 20 });
  });
  it('uses defaults for invalid remote values instead of stale cached values', async () => {
    localStorage.setItem(FONT_STORAGE_KEY, JSON.stringify(local));
    vi.mocked(settingsClient.getPreference).mockResolvedValue('invalid');
    expect(await loadFontSettings()).toEqual(defaults);
    expect(JSON.parse(localStorage.getItem(FONT_STORAGE_KEY)!)).toEqual(defaults);
  });
  it('falls back to normalized local settings if remote rejects', async () => {
    localStorage.setItem(FONT_STORAGE_KEY, JSON.stringify({ ...local, fontSizeUi: 99 }));
    vi.mocked(settingsClient.getPreference).mockRejectedValue(new Error('offline'));
    expect(await loadFontSettings()).toEqual({ ...local, fontSizeUi: 24 });
  });
  it.each([null, '{broken', 'null', '[]'])(
    'returns defaults for missing or malformed cache %j',
    async (cache) => {
      if (cache !== null) localStorage.setItem(FONT_STORAGE_KEY, cache);
      expect(await loadFontSettings()).toEqual(defaults);
    },
  );
  it('continues when localStorage is unavailable', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('denied');
    });
    expect(await loadFontSettings()).toEqual(defaults);
    await expect(saveFontSettings(local)).resolves.toBeUndefined();
    expect(settingsClient.setPreferenceStrict).toHaveBeenCalledWith('font_ui', 'inter', 'ui');
  });
  it('clears pending on recovery success when no concurrent save happens', async () => {
    // Pre-seed a pending snapshot (simulating a prior crashed save).
    localStorage.setItem(FONT_STORAGE_KEY, JSON.stringify({ ...local, pending: true }));
    // Fresh module sees the pending flag on first load.
    vi.resetModules();
    const { loadFontSettings: reload } = await import('../fontStorage');
    vi.mocked(settingsClient.setPreferenceStrict).mockResolvedValue(undefined);
    expect(await reload()).toEqual(local);
    expect(JSON.parse(localStorage.getItem(FONT_STORAGE_KEY)!)).toEqual(local);
  });
  it('serializes recovery with a concurrent user save; newer save wins and clears pending', async () => {
    // Pre-seed pending snapshot `local`.
    localStorage.setItem(FONT_STORAGE_KEY, JSON.stringify({ ...local, pending: true }));
    vi.resetModules();
    const mod = await import('../fontStorage');
    // Hang every IPC call on a gate we control. Both recovery and user save
    // queue behind the same `remoteQueue`, and both call setPreferenceStrict
    // which now never resolves until we release the gate.
    let finish!: () => void;
    const gate = new Promise<void>((resolve) => {
      finish = resolve;
    });
    vi.mocked(settingsClient.setPreferenceStrict).mockImplementation(() => gate);

    const loading = mod.loadFontSettings();
    await Promise.resolve();
    await Promise.resolve();
    // Cache still pending — recovery IPC is blocked on the gate.
    expect(JSON.parse(localStorage.getItem(FONT_STORAGE_KEY)!).pending).toBe(true);
    // User save enqueues behind recovery on the shared remote queue.
    const newer = { ...local, fontSizeUi: 24 };
    const saving = mod.saveFontSettings(newer);
    // Synchronous cache write happens immediately — newer value, still pending.
    expect(JSON.parse(localStorage.getItem(FONT_STORAGE_KEY)!)).toEqual({
      ...newer,
      pending: true,
    });
    // Release the gate. Both saves complete. Because remoteQueue serializes
    // them and `cacheVersion` is shared, recovery sees a stale version and
    // does NOT overwrite the newer edit; user save's version matches and
    // clears pending.
    finish();
    await loading;
    await saving;
    expect(JSON.parse(localStorage.getItem(FONT_STORAGE_KEY)!)).toEqual(newer);
  });
  it('normalizes saves before caching and serializes backend numbers as strings', async () => {
    await saveFontSettings({ ...local, fontUi: 'invalid', fontSizeUi: 9, fontSizeCode: 21.7 });
    expect(JSON.parse(localStorage.getItem(FONT_STORAGE_KEY)!)).toEqual({
      ...local,
      fontUi: 'inter',
      fontSizeUi: 10,
      fontSizeCode: 21,
    });
    expect(settingsClient.setPreferenceStrict).toHaveBeenCalledTimes(4);
    expect(settingsClient.setPreferenceStrict).toHaveBeenCalledWith('font_ui', 'inter', 'ui');
    expect(settingsClient.setPreferenceStrict).toHaveBeenCalledWith('font_code', 'consolas', 'ui');
    expect(settingsClient.setPreferenceStrict).toHaveBeenCalledWith('font_size_ui', '10', 'ui');
    expect(settingsClient.setPreferenceStrict).toHaveBeenCalledWith('font_size_code', '21', 'ui');
  });
});
