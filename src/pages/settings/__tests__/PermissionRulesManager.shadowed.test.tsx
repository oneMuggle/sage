/**
 * R109 已保存规则遮蔽标注:findShadowedRules 纯派生 + 管理器徽标。
 *
 * 覆盖只认等值与插件通配两族(归属只用后端权威 plugin_name 标
 * 注),一般 fnmatch 包含不判 —— 反例与正例同等重要。
 */
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { PermissionRuleDecision, PermissionRuleItem } from '../../../shared/api/permissionApi';
import { I18nProvider } from '../../../shared/lib/i18n';
import { findShadowedRules, PermissionRulesManager } from '../PermissionRulesManager';

const listRulesMock = vi.fn();
vi.mock('../../../shared/api/permissionApi', () => ({
  permissionApi: {
    listRules: (...args: unknown[]) => listRulesMock(...args),
    deleteRule: vi.fn().mockResolvedValue([]),
    clearRules: vi.fn().mockResolvedValue([]),
    deleteRulesByPlugin: vi.fn().mockResolvedValue([]),
    deleteOrphanRules: vi.fn().mockResolvedValue([]),
  },
}));

vi.mock('../../../shared/ui/ConfirmDialog/confirmService', () => ({
  confirmDialog: vi.fn().mockResolvedValue(false),
}));

function rule(
  tool_pattern: string,
  decision: PermissionRuleDecision,
  plugin_name: string | null = null,
  plugin_status: string | null = null,
): PermissionRuleItem {
  return { tool_pattern, decision, plugin_name, plugin_status };
}

describe('findShadowedRules', () => {
  it('flags an equal-pattern allow covered by deny, never the deny itself', () => {
    const shadowed = findShadowedRules([rule('terminal', 'allow'), rule('terminal', 'deny')]);
    expect(shadowed.get(0)).toBe('terminal');
    expect(shadowed.has(1)).toBe(false);
  });

  it('flags an exact plugin allow covered by the whole-plugin wildcard deny', () => {
    const shadowed = findShadowedRules([
      rule('plugin__demo__echo', 'allow', 'demo'),
      rule('plugin__demo__*', 'deny', 'demo'),
    ]);
    expect(shadowed.get(0)).toBe('plugin__demo__*');
  });

  it('flags a plugin wildcard allow covered by the global plugin wildcard deny', () => {
    const shadowed = findShadowedRules([
      rule('plugin__demo__*', 'allow', 'demo'),
      rule('plugin__*', 'deny'),
    ]);
    expect(shadowed.get(0)).toBe('plugin__*');
  });

  it('flags ask covered by an equal-pattern allow (precedence generalization)', () => {
    const shadowed = findShadowedRules([rule('terminal', 'ask'), rule('terminal', 'allow')]);
    expect(shadowed.get(0)).toBe('terminal');
  });

  it('does not flag when coverage is only partial or unrelated', () => {
    // 精确 deny 只盖一个工具,整插件 allow 对其余工具仍生效
    expect(
      findShadowedRules([
        rule('plugin__demo__*', 'allow', 'demo'),
        rule('plugin__demo__echo', 'deny', 'demo'),
      ]).size,
    ).toBe(0);
    // 异插件通配互不覆盖
    expect(
      findShadowedRules([
        rule('plugin__demo__echo', 'allow', 'demo'),
        rule('plugin__other__*', 'deny', 'other'),
      ]).size,
    ).toBe(0);
    // 同决定重复行谁也不遮蔽谁
    expect(findShadowedRules([rule('terminal', 'allow'), rule('terminal', 'allow')]).size).toBe(0);
  });

  it('stays conservative: no general fnmatch inclusion, wildcard classes need annotation', () => {
    // file_* 可能真包含 file_write,但一般 fnmatch 包含不判
    expect(findShadowedRules([rule('file_write', 'allow'), rule('file_*', 'deny')]).size).toBe(0);
    // 无权威归属标注(missing)时插件通配类不触发,只剩等值类
    expect(
      findShadowedRules([
        rule('plugin__ghost__echo', 'allow', null, 'missing'),
        rule('plugin__*', 'deny'),
      ]).size,
    ).toBe(0);
  });
});

describe('PermissionRulesManager shadowed badge', () => {
  beforeEach(() => {
    listRulesMock.mockReset();
  });

  it('renders the shadowed badge with the covering pattern in the title', async () => {
    listRulesMock.mockResolvedValue([
      rule('plugin__demo__echo', 'allow', 'demo'),
      rule('plugin__demo__*', 'deny', 'demo'),
    ]);
    render(
      <I18nProvider>
        <PermissionRulesManager />
      </I18nProvider>,
    );

    const badge = await screen.findByTestId('permission-rule-shadowed-0');
    expect(badge).toHaveTextContent('被遮蔽');
    expect(badge.getAttribute('title')).toContain('plugin__demo__*');
    expect(screen.queryByTestId('permission-rule-shadowed-1')).toBeNull();
  });

  it('renders no badge for an unshadowed list', async () => {
    listRulesMock.mockResolvedValue([rule('terminal', 'allow')]);
    render(
      <I18nProvider>
        <PermissionRulesManager />
      </I18nProvider>,
    );

    expect(await screen.findByTestId('permission-rule-delete-0')).toBeInTheDocument();
    expect(screen.queryByTestId('permission-rule-shadowed-0')).toBeNull();
  });
});
