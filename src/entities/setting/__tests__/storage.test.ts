/**
 * entities/setting/storage 测试
 *
 * 覆盖：
 *   - 无 persistence → 返回 DEFAULT_SETTINGS
 *   - v1 (apiUrl + model) → v2 (endpoints + modelSelections) 迁移
 *   - saveSettings 合并并 stamp version
 *   - 解析失败回退默认值
 *   - resetSettings 写回默认
 */
import { beforeEach, describe, expect, it } from 'vitest';

import { loadSettings, resetSettings, saveSettings } from '../storage';
import {
  DEFAULT_SETTINGS,
  SETTINGS_STORAGE_KEY,
  SETTINGS_VERSION,
  type EndpointConfig,
} from '../types';

beforeEach(() => {
  localStorage.clear();
});

describe('storage.loadSettings', () => {
  it('returns DEFAULT_SETTINGS when no persistence exists', () => {
    const settings = loadSettings();
    expect(settings).toEqual(DEFAULT_SETTINGS);
    // 不能是同一引用 —— 验证创建了副本
    expect(settings).not.toBe(DEFAULT_SETTINGS);
  });

  it('returns DEFAULT_SETTINGS when persisted JSON is corrupt', () => {
    localStorage.setItem(SETTINGS_STORAGE_KEY, '{not valid json');
    expect(loadSettings()).toEqual(DEFAULT_SETTINGS);
  });

  it('migrates legacy v1 schema (apiUrl + model) to v2', () => {
    localStorage.setItem(
      SETTINGS_STORAGE_KEY,
      JSON.stringify({
        version: '1.0.0',
        apiUrl: 'https://legacy.test/v1',
        model: 'gpt-legacy',
        temperature: 0.5,
      }),
    );

    const settings = loadSettings();

    expect(settings.version).toBe(SETTINGS_VERSION);
    expect(settings.endpoints).toHaveLength(1);
    expect(settings.endpoints[0].baseUrl).toBe('https://legacy.test/v1');
    expect(settings.endpoints[0].isActive).toBe(true);
    expect(settings.endpoints[0].discoveredModels[0].id).toBe('gpt-legacy');
    expect(settings.modelSelections.chatModelId).toBe('gpt-legacy');
  });

  it('merges with defaults when version is current v2', () => {
    localStorage.setItem(
      SETTINGS_STORAGE_KEY,
      JSON.stringify({
        version: SETTINGS_VERSION,
        temperature: 0.123,
        // 故意省略 streaming / endpoints 等字段
      }),
    );

    const settings = loadSettings();
    expect(settings.temperature).toBe(0.123);
    expect(settings.streaming).toBe(DEFAULT_SETTINGS.streaming);
    expect(settings.endpoints).toEqual(DEFAULT_SETTINGS.endpoints);
  });
});

describe('storage.saveSettings', () => {
  it('merges partial update with current state and stamps version', () => {
    saveSettings({ temperature: 0.9 });
    const raw = JSON.parse(localStorage.getItem(SETTINGS_STORAGE_KEY)!);
    expect(raw.temperature).toBe(0.9);
    expect(raw.version).toBe(SETTINGS_VERSION);
    // 未指定字段应当继承默认
    expect(raw.maxContext).toBe(DEFAULT_SETTINGS.maxContext);
  });

  it('replaces endpoints when provided', () => {
    const endpoint: EndpointConfig = {
      id: 'a',
      name: 'A',
      baseUrl: 'https://a.test',
      apiKey: 'sk',
      isActive: true,
      discoveredModels: [],
      lastDiscoveredAt: null,
    };
    saveSettings({ endpoints: [endpoint] });
    const raw = JSON.parse(localStorage.getItem(SETTINGS_STORAGE_KEY)!);
    expect(raw.endpoints).toEqual([endpoint]);
  });
});

describe('storage.resetSettings', () => {
  it('writes DEFAULT_SETTINGS to localStorage', () => {
    localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify({ temperature: 9.9 }));
    resetSettings();
    const raw = JSON.parse(localStorage.getItem(SETTINGS_STORAGE_KEY)!);
    expect(raw.temperature).toBe(DEFAULT_SETTINGS.temperature);
    expect(raw.version).toBe(SETTINGS_VERSION);
  });
});
