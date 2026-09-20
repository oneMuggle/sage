import { describe, expect, it, vi } from 'vitest';

import { settingsClient } from '../../../shared/api/settingsClient';
import { readSetting, resetSetting, writeSetting } from '../settingsAdapter';

vi.mock('../../../shared/api/settingsClient', () => ({
  settingsClient: {
    getPreference: vi.fn(),
    setPreferenceStrict: vi.fn(),
    getSettings: vi.fn(),
    setSettings: vi.fn(),
  },
}));

describe('settingsAdapter', () => {
  it('routes preference reads to the KV client', async () => {
    vi.mocked(settingsClient.getPreference).mockResolvedValue('prompt');
    await expect(readSetting('permission_mode')).resolves.toBe('prompt');
    expect(settingsClient.getPreference).toHaveBeenCalledWith('permission_mode');
  });

  it('rejects invalid values before writing', async () => {
    await expect(writeSetting('orch.maxConcurrentSubagents', 0)).rejects.toThrow('小于 1');
    expect(settingsClient.setPreferenceStrict).not.toHaveBeenCalled();
  });

  it('serializes and parses JSON preference values', async () => {
    vi.mocked(settingsClient.setPreferenceStrict).mockResolvedValue(undefined);
    await writeSetting('network_policy', { mode: 'offline', allowed_hosts: [] });
    expect(settingsClient.setPreferenceStrict).toHaveBeenCalledWith(
      'network_policy',
      '{"mode":"offline","allowed_hosts":[]}',
      'general',
    );

    vi.mocked(settingsClient.getPreference).mockResolvedValue('{"mode":"offline"}');
    await expect(readSetting('network_policy')).resolves.toEqual({ mode: 'offline' });
  });

  it('routes update settings through Electron IPC', async () => {
    (window as unknown as { electronAPI: unknown }).electronAPI = {
      updates: {
        getConfig: vi.fn().mockResolvedValue({ channel: 'stable' }),
        setConfigPatch: vi.fn().mockResolvedValue({ channel: 'beta' }),
      },
    };
    await writeSetting('updates.channel', 'beta');
    expect((window.electronAPI as NonNullable<typeof window.electronAPI>).updates.setConfigPatch).toHaveBeenCalledWith({ channel: 'beta' });
  });

  it('writes app_settings top-level values through the settings client', async () => {
    await writeSetting('streaming', false);
    expect(settingsClient.setSettings).toHaveBeenCalledWith({ streaming: false });
  });

  it('resets a setting to its registered default', async () => {
    await resetSetting('streaming');
    expect(settingsClient.setSettings).toHaveBeenCalledWith({ streaming: true });
  });
});
