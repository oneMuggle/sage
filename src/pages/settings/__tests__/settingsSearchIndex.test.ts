/**
 * r108: settingsSearchIndex 不变量与搜索行为测试。
 *
 * 背景：zotero 条目曾被重复登记两次（本批修复），设置搜索返回重复结果。
 * key 唯一性不变量在此锁定，防止同类滑铲复发。
 */
import { describe, expect, it } from 'vitest';

import { searchSettings, SETTINGS_SEARCH_INDEX } from '../settingsSearchIndex';

describe('SETTINGS_SEARCH_INDEX 不变量', () => {
  it('key 全局唯一', () => {
    const keys = SETTINGS_SEARCH_INDEX.map((e) => e.key);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it('每个条目四字段均为非空字符串，keywords 全小写', () => {
    for (const e of SETTINGS_SEARCH_INDEX) {
      expect(e.key.trim(), `key of ${e.key}`).toBeTruthy();
      expect(e.label.trim(), `label of ${e.key}`).toBeTruthy();
      expect(e.labelEn.trim(), `labelEn of ${e.key}`).toBeTruthy();
      expect(e.keywords.trim(), `keywords of ${e.key}`).toBeTruthy();
      expect(e.keywords, `keywords of ${e.key}`).toBe(e.keywords.toLowerCase());
    }
  });

  it('tab 值均在已知 tab 集合内', () => {
    const knownTabs = new Set([
      'general',
      'basic',
      'tools-connections',
      'endpoints',
      'models',
      'orchestration',
      'memory',
      'network',
      'mcp',
      'zotero',
      'runtime',
      'evolution',
      'updates',
      'providers',
      'usage-stats',
    ]);
    for (const e of SETTINGS_SEARCH_INDEX) {
      expect(knownTabs.has(e.tab), `tab of ${e.key}`).toBe(true);
    }
  });

  it('P1-5：不存在已下线的 memory-knowledge tab', () => {
    // 两个「记忆」tab 已合并。索引里若还留着 memory-knowledge，搜索命中会跳到
    // 一个没有内容面板的 tab —— 静默失败，用户只看到空白设置页。
    for (const e of SETTINGS_SEARCH_INDEX) {
      expect(e.tab, `tab of ${e.key}`).not.toBe('memory-knowledge');
    }
  });

  it('P1-5：记忆相关条目全部收敛到同一个 memory tab', () => {
    // IA1 的可执行判据：记忆能力的设置入口只有一个。
    const memoryKeys = [
      'autoMemory',
      'confirmDelete',
      'context_turn_limit',
      'auto_checkpoint',
      'memory_embedding',
      'memory_consolidation',
      'memory_backup',
    ];
    for (const key of memoryKeys) {
      const entry = SETTINGS_SEARCH_INDEX.find((e) => e.key === key);
      expect(entry, `missing index entry ${key}`).toBeTruthy();
      expect(entry?.tab, `tab of ${key}`).toBe('memory');
    }
  });

  it('zotero 条目恰好一个（回归：R108 前重复登记）', () => {
    expect(SETTINGS_SEARCH_INDEX.filter((e) => e.key === 'zotero')).toHaveLength(1);
  });
});

describe('searchSettings', () => {
  it('空/空白查询返回空数组', () => {
    expect(searchSettings('')).toEqual([]);
    expect(searchSettings('   ')).toEqual([]);
  });

  it('命中 label：中文查询返回对应条目', () => {
    const r = searchSettings('主题');
    expect(r.map((e) => e.key)).toContain('theme');
  });

  it('命中 labelEn：英文大小写不敏感', () => {
    const r = searchSettings('ZOTERO');
    expect(r.map((e) => e.key)).toContain('zotero');
  });

  it('命中 keywords 别名：telegram 找到网关条目', () => {
    const r = searchSettings('telegram');
    expect(r.map((e) => e.key)).toContain('gateway');
  });

  it('多词 AND 语义：所有词都须命中', () => {
    expect(searchSettings('font size').map((e) => e.key)).toContain('font_size_ui');
    expect(searchSettings('font 不存在的词').map((e) => e.key)).toHaveLength(0);
  });

  it('无命中返回空数组且不抛错', () => {
    expect(searchSettings('完全不存在的设置项xyz')).toEqual([]);
  });
});
