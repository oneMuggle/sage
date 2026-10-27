/**
 * R110 findPluginToolOwner：精确工具名对生命周期权威名的结构化
 * 归属——长名优先、只认名单内的名字、形状先行；不切分工具名猜名。
 * （findShadowedRules 的用例在 PermissionRulesManager.shadowed 套件。）
 */
import { describe, expect, it } from 'vitest';

import { findPluginToolOwner } from '../permissionInsights';

describe('findPluginToolOwner', () => {
  it('attributes an exact namespaced tool to its plugin', () => {
    expect(findPluginToolOwner('plugin__demo__echo', ['demo'])).toBe('demo');
    // capability 名里再含 __ 不影响归属
    expect(findPluginToolOwner('plugin__demo__read__file', ['demo'])).toBe('demo');
  });

  it('prefers the longest authoritative name (a vs a__b)', () => {
    expect(findPluginToolOwner('plugin__a__b__run', ['a', 'a__b'])).toBe('a__b');
    expect(findPluginToolOwner('plugin__a__b__run', ['a__b', 'a'])).toBe('a__b');
    expect(findPluginToolOwner('plugin__a__run', ['a', 'a__b'])).toBe('a');
  });

  it('returns null for non-plugin names, wildcards and malformed shapes', () => {
    expect(findPluginToolOwner('write_file', ['demo'])).toBeNull();
    expect(findPluginToolOwner('plugin__*', ['demo'])).toBeNull();
    expect(findPluginToolOwner('plugin__demo__*', ['demo'])).toBeNull();
    expect(findPluginToolOwner('plugin__demo', ['demo'])).toBeNull();
    expect(findPluginToolOwner('plugin__demo__', ['demo'])).toBeNull();
    expect(findPluginToolOwner('plugin__demo*', ['demo'])).toBeNull();
  });

  it('returns null when the plugin is absent from the authority list', () => {
    expect(findPluginToolOwner('plugin__demo__echo', ['other'])).toBeNull();
    expect(findPluginToolOwner('plugin__demo__echo', [])).toBeNull();
  });

  it('degrades to null when the lifecycle list is unavailable', () => {
    expect(findPluginToolOwner('plugin__demo__echo', null)).toBeNull();
  });
});
