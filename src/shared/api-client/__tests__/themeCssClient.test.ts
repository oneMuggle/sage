import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ActiveTheme, ThemePreset, ThemeValidationResult } from '../../types/theme';

// Mock the electron API surface that preload.ts will expose
const mockElectronAPI = {
  theme: {
    list: vi.fn(),
    get: vi.fn(),
    save: vi.fn(),
    delete: vi.fn(),
    getActive: vi.fn(),
    saveActive: vi.fn(),
    validate: vi.fn(),
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  // Inject mock into window
  (global as any).window = { electronAPI: mockElectronAPI };
});

import {
  deleteTheme,
  getActiveTheme,
  getTheme,
  listThemes,
  saveActiveTheme,
  saveTheme,
  validateThemeCss,
} from '../themeCssClient';

describe('listThemes', () => {
  it('returns parsed ApiResponse on success', async () => {
    const presets: ThemePreset[] = [{ id: 'light', name: 'n', description: 'd' }];
    mockElectronAPI.theme.list.mockResolvedValue({ success: true, data: presets });
    const result = await listThemes();
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data).toEqual(presets);
    }
  });

  it('returns error envelope on failure', async () => {
    mockElectronAPI.theme.list.mockResolvedValue({ success: false, error: 'IPC timeout' });
    const result = await listThemes();
    expect(result.success).toBe(false);
  });
});

describe('getTheme', () => {
  it('passes id to IPC', async () => {
    mockElectronAPI.theme.get.mockResolvedValue({
      success: true,
      data: { id: 'ocean', name: 'n', description: 'd' },
    });
    await getTheme('ocean');
    expect(mockElectronAPI.theme.get).toHaveBeenCalledWith('ocean');
  });
});

describe('saveTheme', () => {
  it('passes preset payload to IPC', async () => {
    const preset: ThemePreset = { id: 'forest', name: 'n', description: 'd' };
    mockElectronAPI.theme.save.mockResolvedValue({ success: true, data: preset });
    await saveTheme(preset);
    expect(mockElectronAPI.theme.save).toHaveBeenCalledWith(preset);
  });
});

describe('deleteTheme', () => {
  it('passes id to IPC', async () => {
    mockElectronAPI.theme.delete.mockResolvedValue({ success: true, data: { deleted: 'light' } });
    await deleteTheme('light');
    expect(mockElectronAPI.theme.delete).toHaveBeenCalledWith('light');
  });
});

describe('getActiveTheme', () => {
  it('returns ActiveTheme', async () => {
    const active: ActiveTheme = { presetId: 'dark' };
    mockElectronAPI.theme.getActive.mockResolvedValue({ success: true, data: active });
    const result = await getActiveTheme();
    expect(result).toEqual({ success: true, data: active });
  });
});

describe('saveActiveTheme', () => {
  it('passes payload to IPC', async () => {
    const active: ActiveTheme = { presetId: 'ocean', customCss: ':root {}' };
    mockElectronAPI.theme.saveActive.mockResolvedValue({ success: true, data: active });
    await saveActiveTheme(active);
    expect(mockElectronAPI.theme.saveActive).toHaveBeenCalledWith(active);
  });
});

describe('validateThemeCss', () => {
  it('passes css to IPC', async () => {
    const result: ThemeValidationResult = { valid: true };
    mockElectronAPI.theme.validate.mockResolvedValue({ success: true, data: result });
    await validateThemeCss(':root {}');
    expect(mockElectronAPI.theme.validate).toHaveBeenCalledWith(':root {}');
  });
});

describe('graceful degradation when window.electronAPI is missing', () => {
  it('returns error envelope, not throw', async () => {
    (global as any).window = {}; // no electronAPI
    const result = await listThemes();
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.code).toBe('IPC_UNAVAILABLE');
    }
  });
});
