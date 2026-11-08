import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { SETTINGS_SEARCH_INDEX } from '../settingsSearchIndex';
import { SETTINGS_TABS, SETTINGS_TAB_KEYS } from '../settingsTabs';

/**
 * Tab 注册表守卫 —— §4.2 搜索索引防漂移。
 *
 * P2 (2026-10-28): tab 元数据（key / labelKey / group / aliases / render）
 * 已经统一收进 `settingsTabs.tsx`，但搜索索引仍是手写的 86 条。新增设置项
 * 容易忘登记搜索索引、或登记了错误的 `tab`，或给 `<SettingRow>` 加的
 * `anchor="..."` 字面量在索引里没有对应条目。本文件把三条守卫集中到
 * 一个地方，让漏登记在 CI 上立刻红。
 *
 * 注意：本守卫只扫 `anchor="..."` 字面量；`anchor={variable}` 形式的
 * 动态锚点（如 `FontSettingsSection` 里的字体族/字号派生锚点）不在此处覆盖，
 * 由对应的组件级测试单独负责。
 */

const SETTINGS_DIR = join(dirname(fileURLToPath(import.meta.url)), '..');

function readTabSources(): { name: string; content: string }[] {
  return readdirSync(SETTINGS_DIR)
    .filter((name) => name.endsWith('.tsx') && !name.endsWith('.test.tsx'))
    .map((name) => ({
      name,
      content: readFileSync(join(SETTINGS_DIR, name), 'utf8'),
    }));
}

function extractLiteralAnchors(content: string): string[] {
  // 排除模板字面量内容（`[data-settings-anchor="${...}"]` 等），只保留静态字符串锚点。
  const matches = content.matchAll(/\banchor="([^"]+)"/g);
  return Array.from(matches, (m) => m[1]).filter((value) => !value.includes('${'));
}

describe('settings tab registry guards', () => {
  it('every literal anchor in settings tabs has a matching search-index entry', () => {
    const indexedKeys = new Set(SETTINGS_SEARCH_INDEX.map((entry) => entry.key));
    const missing: { file: string; anchor: string }[] = [];
    for (const { name, content } of readTabSources()) {
      for (const anchor of extractLiteralAnchors(content)) {
        if (!indexedKeys.has(anchor)) missing.push({ file: name, anchor });
      }
    }
    expect(missing).toEqual([]);
  });

  it('every search-index entry points to a registered tab key', () => {
    const registered = new Set<string>(SETTINGS_TAB_KEYS);
    const stale = SETTINGS_SEARCH_INDEX.filter((entry) => !registered.has(entry.tab));
    expect(stale.map((entry) => ({ key: entry.key, tab: entry.tab }))).toEqual([]);
  });

  it('every visible tab has at least one search-index entry', () => {
    const indexed = new Set(SETTINGS_SEARCH_INDEX.map((entry) => entry.tab));
    const orphanTabs = SETTINGS_TABS.map((tab) => tab.key).filter((key) => !indexed.has(key));
    expect(orphanTabs).toEqual([]);
  });

  it('the registry contains the expected tab count', () => {
    // 16（main 基线）+ 1 feedback（上游 #2654）+ 1 audit-export（P3）+ 1 pet = 19
    expect(SETTINGS_TABS.length).toBe(19);
  });
});
