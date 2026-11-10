import { describe, expect, it } from 'vitest';

import type { RuleEntry } from '../../../shared/api/rulesApi';
import {
  buildRuleGroups,
  conflictedRuleIds,
  countEnabled,
  filterRules,
  layerLabelKey,
  sortEffectiveRules,
  sourceDetail,
} from '../rulesView';

function rule(overrides: Partial<RuleEntry> & Pick<RuleEntry, 'id' | 'layer'>): RuleEntry {
  return {
    sourceLabel: '项目规则',
    scope: '全局',
    category: 'coding_style',
    content: '使用双引号',
    enabled: true,
    editable: 'full',
    priority: 5,
    trigger: null,
    updatedAt: null,
    origin: null,
    ...overrides,
  };
}

describe('rulesView', () => {
  it('groups entries in injection-layer order and drops empty layers', () => {
    const groups = buildRuleGroups([
      rule({ id: 'constraint:1', layer: 'constraint' }),
      rule({ id: 'global:#0', layer: 'global' }),
    ]);

    expect(groups.map((group) => group.layer)).toEqual(['global', 'constraint']);
  });

  it('filters by layer and by case-insensitive search across fields', () => {
    const entries = [
      rule({ id: 'constraint:1', layer: 'constraint', content: '使用双引号' }),
      rule({ id: 'doc:SAGE.md#0', layer: 'doc', content: 'Run PYTEST before commit' }),
    ];

    expect(filterRules(entries, { search: '', layer: 'doc' })).toHaveLength(1);
    expect(filterRules(entries, { search: 'pytest', layer: 'all' })).toEqual([entries[1]]);
    expect(filterRules(entries, { search: '不存在', layer: 'all' })).toEqual([]);
  });

  it('counts only enabled rules', () => {
    expect(
      countEnabled([
        rule({ id: 'constraint:1', layer: 'constraint' }),
        rule({ id: 'constraint:2', layer: 'constraint', enabled: false }),
      ]),
    ).toBe(1);
  });

  it('collects both sides of every conflict', () => {
    const ids = conflictedRuleIds([
      { a: 'constraint:1', b: 'doc:SAGE.md#0', category: 'coding_style', triggers: [null, null] },
    ]);

    expect([...ids].sort()).toEqual(['constraint:1', 'doc:SAGE.md#0']);
  });

  it('orders effective rules by layer and puts content checks last within a stage', () => {
    const ordered = sortEffectiveRules([
      rule({ id: 'playbook:s1:check:a:c1', layer: 'playbook' }),
      rule({ id: 'constraint:1', layer: 'constraint' }),
      rule({ id: 'playbook:s1:0', layer: 'playbook' }),
      rule({ id: 'global:#0', layer: 'global' }),
    ]);

    expect(ordered.map((entry) => entry.id)).toEqual([
      'global:#0',
      'constraint:1',
      'playbook:s1:0',
      'playbook:s1:check:a:c1',
    ]);
  });

  it('maps every layer filter to a translation key', () => {
    expect(layerLabelKey('all')).toBe('rules.filter.all');
    expect(layerLabelKey('playbook')).toBe('rules.layer.playbook');
  });

  it('shows only the file name for path-shaped scopes and keeps the full path as tooltip', () => {
    expect(
      sourceDetail(
        rule({ id: 'doc:SAGE.md#0', layer: 'doc', scope: '/home/fz/project/sage/SAGE.md' }),
      ),
    ).toEqual({ text: 'SAGE.md', title: '/home/fz/project/sage/SAGE.md' });

    expect(
      sourceDetail(
        rule({ id: 'doc:CLAUDE.md#1', layer: 'doc', scope: 'C:\\work\\sage\\CLAUDE.md' }),
      ),
    ).toEqual({ text: 'CLAUDE.md', title: 'C:\\work\\sage\\CLAUDE.md' });
  });

  it('keeps non-path scopes verbatim and omits the global layer', () => {
    expect(
      sourceDetail(rule({ id: 'playbook:s1:0', layer: 'playbook', scope: '需求分析' })),
    ).toEqual({
      text: '需求分析',
    });
    expect(sourceDetail(rule({ id: 'global:#0', layer: 'global', scope: '全局' }))).toBeNull();
    expect(sourceDetail(rule({ id: 'constraint:1', layer: 'constraint', scope: '  ' }))).toBeNull();
  });
});
