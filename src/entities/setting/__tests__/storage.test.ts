/**
 * entities/setting/storage 测试
 *
 * 覆盖：
 *   - 无 persistence → 返回 DEFAULT_SETTINGS
 *   - v1 (apiUrl + model) → v3 (endpoints + ModelSelection bindings) 迁移
 *   - v2 (isActive + flat modelSelections) → v3 迁移
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

  it('migrates legacy v1 schema (apiUrl + model) to v3', () => {
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
    expect(settings.endpoints[0]).not.toHaveProperty('isActive');
    expect(settings.endpoints[0].discoveredModels[0].id).toBe('gpt-legacy');
    expect(settings.modelSelections.chatModel.modelId).toBe('gpt-legacy');
    expect(settings.modelSelections.chatModel.endpointId).toBe(settings.endpoints[0].id);
  });

  it('migrates v2 schema (isActive + flat modelSelections) to v3', () => {
    const ep1Id = 'ep-1-uuid';
    const ep2Id = 'ep-2-uuid';
    localStorage.setItem(
      SETTINGS_STORAGE_KEY,
      JSON.stringify({
        version: '2.0.0',
        endpoints: [
          {
            id: ep1Id,
            name: 'OpenAI',
            baseUrl: 'https://api.openai.com/v1',
            apiKey: 'sk-1',
            isActive: false,
            discoveredModels: [{ id: 'gpt-4o', capabilities: ['chat'], endpointId: ep1Id }],
            lastDiscoveredAt: null,
          },
          {
            id: ep2Id,
            name: 'Ollama',
            baseUrl: 'http://localhost:11434/v1',
            apiKey: '',
            isActive: true,
            discoveredModels: [{ id: 'llama3', capabilities: ['chat'], endpointId: ep2Id }],
            lastDiscoveredAt: null,
          },
        ],
        modelSelections: {
          chatModelId: 'llama3',
          visionModelId: null,
          embeddingModelId: null,
        },
        temperature: 0.7,
      }),
    );

    const settings = loadSettings();

    expect(settings.version).toBe(SETTINGS_VERSION);
    // isActive stripped from all endpoints
    expect(settings.endpoints[0]).not.toHaveProperty('isActive');
    expect(settings.endpoints[1]).not.toHaveProperty('isActive');
    // model selection bound to the previously-active endpoint
    expect(settings.modelSelections.chatModel.endpointId).toBe(ep2Id);
    expect(settings.modelSelections.chatModel.modelId).toBe('llama3');
    // null selections remain unbound
    expect(settings.modelSelections.visionModel.endpointId).toBeNull();
    expect(settings.modelSelections.visionModel.modelId).toBeNull();
  });

  it('merges with defaults when version is current v3', () => {
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
