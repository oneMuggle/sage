/**
 * R41: 设置页搜索过滤纯函数测试。
 */
import { describe, expect, it } from 'vitest';

interface TabEntry {
  key: string;
  label: string;
}

// 从 Settings.tsx 抽出的过滤逻辑（与实现一致）
function filterTabs(tabs: TabEntry[], query: string): TabEntry[] {
  const q = query.trim().toLowerCase();
  if (!q) return tabs;
  return tabs.filter((t) => t.label.toLowerCase().includes(q));
}

const TABS: TabEntry[] = [
  { key: 'general', label: '通用' },
  { key: 'endpoints', label: '端点' },
  { key: 'models', label: '模型' },
  { key: 'memory', label: '记忆' },
  { key: 'network', label: '网络' },
  { key: 'prompts', label: '提示词' },
  { key: 'mcp', label: 'MCP' },
  { key: 'runtime', label: '开发环境' },
  { key: 'evolution', label: '进化' },
  { key: 'updates', label: '更新' },
];

describe('filterTabs — R41 设置搜索', () => {
  it('空查询返回全部', () => {
    expect(filterTabs(TABS, '')).toHaveLength(TABS.length);
    expect(filterTabs(TABS, '  ')).toHaveLength(TABS.length);
  });

  it('匹配 label 子串（大小写不敏感）', () => {
    expect(filterTabs(TABS, '端点')).toEqual([{ key: 'endpoints', label: '端点' }]);
    expect(filterTabs(TABS, 'mcp')).toEqual([{ key: 'mcp', label: 'MCP' }]);
  });

  it('无匹配返回空数组', () => {
    expect(filterTabs(TABS, '不存在的')).toEqual([]);
  });
});
