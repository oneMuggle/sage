import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockGetSettings = vi.fn();
const mockSetSettings = vi.fn();
vi.mock('../../../shared/api/settingsClient', () => ({
  settingsClient: {
    getSettings: (...args: unknown[]) => mockGetSettings(...args),
    setSettings: (...args: unknown[]) => mockSetSettings(...args),
  },
}));

import { loadSettings, mergeWithDefaults, saveSettings, resetSettings } from '../storage';
import type { AppSettings } from '../types';
import { DEFAULT_SETTINGS, SETTINGS_STORAGE_KEY } from '../types';

const CACHE_KEY = SETTINGS_STORAGE_KEY; // 'sage-settings'
const MIGRATION_MARKER = 'sage-settings.migrated_to_backend';

describe('settings storage (async)', () => {
  beforeEach(() => {
    localStorage.clear();
    mockGetSettings.mockReset();
    mockSetSettings.mockReset();
  });

  describe('loadSettings', () => {
    it('后端命中时返回 backend 数据并写 local cache', async () => {
      const remoteData = { ...DEFAULT_SETTINGS, maxContext: 8000 };
      mockGetSettings.mockResolvedValue(remoteData);
      const r = await loadSettings();
      expect(r.maxContext).toBe(8000);
      expect(JSON.parse(localStorage.getItem(CACHE_KEY)!).maxContext).toBe(8000);
    });

    it('后端无值且 localStorage 有值时回退 local', async () => {
      mockGetSettings.mockResolvedValue(null);
      const local = { ...DEFAULT_SETTINGS, temperature: 0.3 };
      localStorage.setItem(CACHE_KEY, JSON.stringify(local));
      const r = await loadSettings();
      expect(r.temperature).toBe(0.3);
    });

    it('都为空时返回 DEFAULT_SETTINGS', async () => {
      mockGetSettings.mockResolvedValue(null);
      const r = await loadSettings();
      expect(r).toEqual(DEFAULT_SETTINGS);
    });

    it('后端失败时降级 localStorage', async () => {
      mockGetSettings.mockResolvedValue(null);
      const local = { ...DEFAULT_SETTINGS, confirmDelete: false };
      localStorage.setItem(CACHE_KEY, JSON.stringify(local));
      const r = await loadSettings();
      expect(r.confirmDelete).toBe(false);
    });
  });

  describe('自动迁移', () => {
    it('首次后端命中 + localStorage 有值 + 未标记迁移 → 自动上传', async () => {
      const local = { ...DEFAULT_SETTINGS, maxContext: 9999 };
      localStorage.setItem(CACHE_KEY, JSON.stringify(local));
      mockGetSettings.mockResolvedValueOnce(null); // 第一次：后端无
      mockSetSettings.mockResolvedValueOnce(undefined);

      await loadSettings();

      expect(mockSetSettings).toHaveBeenCalledWith(expect.objectContaining({ maxContext: 9999 }));
      expect(localStorage.getItem(MIGRATION_MARKER)).toBeTruthy();
    });

    it('已标记迁移时不重复上传', async () => {
      const local = { ...DEFAULT_SETTINGS, maxContext: 9999 };
      localStorage.setItem(CACHE_KEY, JSON.stringify(local));
      localStorage.setItem(MIGRATION_MARKER, '2026-06-22T00:00:00.000Z');
      mockGetSettings.mockResolvedValueOnce(null);

      await loadSettings();

      expect(mockSetSettings).not.toHaveBeenCalled();
    });

    it('后端已有数据时不触发迁移', async () => {
      const local = { ...DEFAULT_SETTINGS, maxContext: 9999 };
      localStorage.setItem(CACHE_KEY, JSON.stringify(local));
      mockGetSettings.mockResolvedValueOnce({ ...DEFAULT_SETTINGS, maxContext: 8000 });

      await loadSettings();

      expect(mockSetSettings).not.toHaveBeenCalled();
    });
  });

  describe('saveSettings', () => {
    it('同步写 localStorage', async () => {
      await saveSettings({ maxContext: 16000 });
      const cached = JSON.parse(localStorage.getItem(CACHE_KEY)!);
      expect(cached.maxContext).toBe(16000);
    });

    it('异步调 setSettings', async () => {
      mockSetSettings.mockResolvedValueOnce(undefined);
      await saveSettings({ maxContext: 16000 });
      expect(mockSetSettings).toHaveBeenCalledWith({ maxContext: 16000 });
    });
  });

  describe('resetSettings', () => {
    it('重置为 DEFAULT_SETTINGS 并写 local + 后端', async () => {
      mockSetSettings.mockResolvedValueOnce(undefined);
      await resetSettings();
      const cached = JSON.parse(localStorage.getItem(CACHE_KEY)!);
      expect(cached).toEqual(DEFAULT_SETTINGS);
      expect(mockSetSettings).toHaveBeenCalled();
    });
  });

  describe('7 天保留清理', () => {
    it('迁移标记 >7 天时清理 localStorage 冗余数据', async () => {
      const local = { ...DEFAULT_SETTINGS, maxContext: 9999 };
      localStorage.setItem(CACHE_KEY, JSON.stringify(local));
      // 标记 8 天前
      const eightDaysAgo = new Date(Date.now() - 8 * 24 * 60 * 60 * 1000).toISOString();
      localStorage.setItem(MIGRATION_MARKER, eightDaysAgo);
      mockGetSettings.mockResolvedValueOnce({ ...DEFAULT_SETTINGS, maxContext: 8000 });

      await loadSettings();

      // 8 天前的标记 + 后端已有数据 → 清理 local
      expect(mockSetSettings).not.toHaveBeenCalled();
    });
  });
});

describe('mergeWithDefaults (orch 嵌套 merge)', () => {
  it('mergeWithDefaults merges orch nested, not replaces', () => {
    // P2-9: 部分 orch 更新不丢其余键（同 endpoints 的既有 bug 防护）。
    const merged = mergeWithDefaults({ orch: { maxRetries: 5 } } as Partial<AppSettings>);
    expect(merged.orch.maxRetries).toBe(5);
    expect(merged.orch.maxConcurrentSubagents).toBe(4); // 其余键保持默认
  });
});

describe('mergeWithDefaults (endpoints / modelSelections deepMerge)', () => {
  it('endpoints 缺省时返回 DEFAULT_SETTINGS.endpoints', () => {
    const merged = mergeWithDefaults({} as Partial<AppSettings>);
    expect(merged.endpoints).toEqual(DEFAULT_SETTINGS.endpoints);
  });

  it('endpoints 提供新 id 时保留用户 endpoint (DEFAULT 为空时也不丢)', () => {
    // Task 1 round 1 (2026-08-24): DEFAULT_SETTINGS 当前 endpoints 为空;
    // deepMerge 仍必须保留用户新 id, 而不是因默认数组兜底逻辑被吞掉.
    const userExtra = {
      id: 'user-added-endpoint',
      name: 'User Added',
      baseUrl: 'http://example.com',
      protocol: 'openai-compatible' as const,
      modelId: null,
      localModelPath: null,
      apiKey: null,
      discoveredModels: [],
      lastDiscoveredAt: null,
    };
    const merged = mergeWithDefaults({
      endpoints: [userExtra],
    } as unknown as Partial<AppSettings>);
    expect(merged.endpoints).toContainEqual(userExtra);
  });

  it('endpoints 采用 deepMerge 返回新数组, 不直接复用 partial 引用', () => {
    const userEndpoint = {
      id: 'user-endpoint',
      name: 'User Endpoint',
      baseUrl: 'http://example.com',
      protocol: 'openai-compatible' as const,
      modelId: 'custom-model',
      localModelPath: null,
      apiKey: 'redacted',
      discoveredModels: [],
      lastDiscoveredAt: null,
    };
    const partial = { endpoints: [userEndpoint] } as unknown as Partial<AppSettings>;
    const merged = mergeWithDefaults(partial);
    expect(merged.endpoints).toEqual([userEndpoint]);
    expect(merged.endpoints).not.toBe(partial.endpoints);
  });

  it('modelSelections 提供部分键时与 DEFAULT 字段级 merge', () => {
    const merged = mergeWithDefaults({
      modelSelections: { chatModel: { endpointId: 'ep-1', modelId: 'm-1' } } as {
        chatModel: { endpointId: string; modelId: string };
      },
    } as Partial<AppSettings>);
    expect(merged.modelSelections.chatModel.endpointId).toBe('ep-1');
    // visionModel / embeddingModel 应保持 DEFAULT (不被丢)
    expect(merged.modelSelections.visionModel).toEqual(
      DEFAULT_SETTINGS.modelSelections.visionModel,
    );
    expect(merged.modelSelections.embeddingModel).toEqual(
      DEFAULT_SETTINGS.modelSelections.embeddingModel,
    );
  });
});
