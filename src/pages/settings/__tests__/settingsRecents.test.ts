// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from 'vitest';

import {
  MAX_SETTINGS_RECENTS,
  SETTINGS_RECENTS_STORAGE_KEY,
  loadSettingsRecents,
  pushSettingsRecent,
  sanitizeSettingsRecents,
  saveSettingsRecents,
} from '../settingsRecents';

beforeEach(() => {
  localStorage.clear();
});

describe('sanitizeSettingsRecents', () => {
  it('returns an empty list for missing or malformed storage', () => {
    expect(sanitizeSettingsRecents(null)).toEqual([]);
    expect(sanitizeSettingsRecents('not json')).toEqual([]);
    expect(sanitizeSettingsRecents('{"a":1}')).toEqual([]);
  });

  it('drops tab keys that no longer exist in the registry', () => {
    // general / memory-knowledge 在 P0/P1 已下线 —— 旧持久化值不能再渲染成死按钮。
    expect(sanitizeSettingsRecents('["general","memory-knowledge","memory"]')).toEqual(['memory']);
  });

  it('de-duplicates while preserving order and caps the list', () => {
    expect(sanitizeSettingsRecents('["network","network","memory"]')).toEqual([
      'network',
      'memory',
    ]);
    expect(sanitizeSettingsRecents('["network","memory","basic","mcp","zotero"]')).toHaveLength(
      MAX_SETTINGS_RECENTS,
    );
  });

  it('ignores non-string entries', () => {
    expect(sanitizeSettingsRecents('["network",42,null,{"key":"mcp"}]')).toEqual(['network']);
  });
});

describe('pushSettingsRecent', () => {
  it('moves an existing tab to the front instead of duplicating it', () => {
    expect(pushSettingsRecent(['network', 'memory'], 'memory')).toEqual(['memory', 'network']);
  });

  it('prepends new tabs and keeps at most MAX_SETTINGS_RECENTS entries', () => {
    expect(pushSettingsRecent(['memory', 'network', 'basic'], 'mcp')).toEqual([
      'mcp',
      'memory',
      'network',
    ]);
  });
});

describe('load/save', () => {
  it('round-trips through localStorage', () => {
    saveSettingsRecents(['network', 'memory']);
    expect(localStorage.getItem(SETTINGS_RECENTS_STORAGE_KEY)).toBe('["network","memory"]');
    expect(loadSettingsRecents()).toEqual(['network', 'memory']);
  });

  it('degrades to an empty list when storage holds junk', () => {
    localStorage.setItem(SETTINGS_RECENTS_STORAGE_KEY, '[]garbage');
    expect(loadSettingsRecents()).toEqual([]);
  });
});
