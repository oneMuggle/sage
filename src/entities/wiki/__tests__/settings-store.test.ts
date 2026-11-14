import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  get: vi.fn(),
  update: vi.fn(),
}));

vi.mock('../../../shared/api-client/wiki', () => ({
  getWikiSettings: api.get,
  updateWikiSettings: api.update,
}));

import { useWikiSettingsStore } from '../settings-store';

const SETTINGS = {
  task_routing: { chat_model: 'm-chat', ingest_model: null, research_model: null },
  reasoning: { chat_mode: 'high' as const, ingest_mode: 'off' as const },
};

beforeEach(() => {
  vi.clearAllMocks();
  useWikiSettingsStore.getState().reset();
});

describe('loadSettings', () => {
  it('loads settings and records the project path', async () => {
    api.get.mockResolvedValue(SETTINGS);

    await useWikiSettingsStore.getState().loadSettings('/proj');

    expect(api.get).toHaveBeenCalledWith('/proj');
    expect(useWikiSettingsStore.getState().settings).toEqual(SETTINGS);
    expect(useWikiSettingsStore.getState().loadedProjectPath).toBe('/proj');
    expect(useWikiSettingsStore.getState().isLoading).toBe(false);
  });

  it('surfaces errors without throwing', async () => {
    api.get.mockRejectedValue(new Error('boom'));

    await useWikiSettingsStore.getState().loadSettings('/proj');

    expect(useWikiSettingsStore.getState().error).toContain('boom');
    expect(useWikiSettingsStore.getState().isLoading).toBe(false);
  });
});

describe('saveSettings', () => {
  it('persists via the API and returns true', async () => {
    api.update.mockResolvedValue(SETTINGS);

    const ok = await useWikiSettingsStore.getState().saveSettings('/proj', SETTINGS);

    expect(api.update).toHaveBeenCalledWith('/proj', SETTINGS);
    expect(ok).toBe(true);
    expect(useWikiSettingsStore.getState().settings).toEqual(SETTINGS);
    expect(useWikiSettingsStore.getState().isSaving).toBe(false);
  });

  it('returns false and records the error on failure', async () => {
    api.update.mockRejectedValue(new Error('nope'));

    const ok = await useWikiSettingsStore.getState().saveSettings('/proj', SETTINGS);

    expect(ok).toBe(false);
    expect(useWikiSettingsStore.getState().error).toContain('nope');
    expect(useWikiSettingsStore.getState().isSaving).toBe(false);
  });
});
