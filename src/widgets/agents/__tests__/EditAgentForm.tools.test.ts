import { describe, expect, it } from 'vitest';

import {
  findPluginToolWildcardCover,
  formatAgentToolsInput,
  parseAgentToolsInput,
  pluginToolSelectionState,
  toggleAgentToolSelection,
} from '../EditAgentForm';

describe('EditAgentForm tools text helpers (R92)', () => {
  it('splits on whitespace/commas, dedupes and keeps first-seen order', () => {
    expect(parseAgentToolsInput(' read_file\nbash, read_file\tlist_dir \n')).toEqual([
      'read_file',
      'bash',
      'list_dir',
    ]);
  });

  it('preserves plugin exact names and wildcard entries verbatim', () => {
    expect(parseAgentToolsInput('plugin__demo__hello\nplugin__demo__*\nplugin__*')).toEqual([
      'plugin__demo__hello',
      'plugin__demo__*',
      'plugin__*',
    ]);
  });

  it('maps empty or separator-only text to an empty tool list', () => {
    expect(parseAgentToolsInput('')).toEqual([]);
    expect(parseAgentToolsInput(' \n, , \t')).toEqual([]);
  });

  it('formats one tool per line and tolerates undefined', () => {
    expect(formatAgentToolsInput(['read_file', 'plugin__demo__*'])).toBe(
      'read_file\nplugin__demo__*',
    );
    expect(formatAgentToolsInput(undefined)).toBe('');
  });
});

describe('EditAgentForm running plugin tool helpers (R94/R98)', () => {
  it('recognizes only the two legal plugin wildcard forms as coverage', () => {
    const toolName = 'plugin__demo__hello';
    expect(findPluginToolWildcardCover(['plugin__*'], toolName, 'demo')).toBe('plugin__*');
    expect(findPluginToolWildcardCover(['plugin__demo__*'], toolName, 'demo')).toBe(
      'plugin__demo__*',
    );
    expect(
      findPluginToolWildcardCover(['plugin__other__*'], toolName, 'demo'),
    ).toBeUndefined();
    expect(
      findPluginToolWildcardCover(['plugin__*'], 'read_file', 'demo'),
    ).toBeUndefined();
    expect(
      findPluginToolWildcardCover(['plugin__demo*'], toolName, 'demo'),
    ).toBeUndefined();
    expect(
      findPluginToolWildcardCover(['plugin__demo__he*'], toolName, 'demo'),
    ).toBeUndefined();
    // R98：capability 名或插件名含 __ 时按权威身份精确覆盖（与后端同口径，
    // 不再像旧字符串镜像那样一律不算覆盖）
    expect(
      findPluginToolWildcardCover(
        ['plugin__demo__*'],
        'plugin__demo__nested__tool',
        'demo',
      ),
    ).toBe('plugin__demo__*');
    expect(
      findPluginToolWildcardCover(
        ['plugin__de__mo__*'],
        'plugin__de__mo__tool',
        'de__mo',
      ),
    ).toBe('plugin__de__mo__*');
  });

  it('does not cover by string prefix when identity differs or is missing (R98)', () => {
    // 字符串同前缀但真实插件是 a__b：插件 a 的通配不算覆盖
    expect(
      findPluginToolWildcardCover(['plugin__a__*'], 'plugin__a__b__c', 'a__b'),
    ).toBeUndefined();
    expect(
      findPluginToolWildcardCover(['plugin__a__b__*'], 'plugin__a__b__c', 'a__b'),
    ).toBe('plugin__a__b__*');
    // 身份缺失时一律不算覆盖（与后端不可见一致），plugin__* 也不行
    expect(
      findPluginToolWildcardCover(['plugin__*'], 'plugin__demo__hello'),
    ).toBeUndefined();
    expect(
      findPluginToolWildcardCover(['plugin__demo__*'], 'plugin__demo__hello'),
    ).toBeUndefined();
    // 工具名与给定 pluginName 不自洽时不算覆盖
    expect(
      findPluginToolWildcardCover(
        ['plugin__demo__*'],
        'plugin__other__hello',
        'demo',
      ),
    ).toBeUndefined();
  });

  it('separates exact selection from wildcard-only coverage', () => {
    expect(
      pluginToolSelectionState(['plugin__demo__*'], 'plugin__demo__hello', 'demo'),
    ).toEqual({
      selected: true,
      exact: false,
      coveredBy: 'plugin__demo__*',
    });
    expect(
      pluginToolSelectionState(
        ['plugin__demo__hello', 'plugin__demo__*'],
        'plugin__demo__hello',
        'demo',
      ),
    ).toEqual({
      selected: true,
      exact: true,
      coveredBy: 'plugin__demo__*',
    });
    expect(pluginToolSelectionState([], 'plugin__demo__hello', 'demo')).toEqual({
      selected: false,
      exact: false,
    });
    // R98：无发布身份时通配不产生覆盖
    expect(
      pluginToolSelectionState(['plugin__demo__*'], 'plugin__demo__hello'),
    ).toEqual({
      selected: false,
      exact: false,
    });
  });

  it('toggles only exact names while preserving wildcards and other entries', () => {
    const entries = ['read_file', 'plugin__demo__*', 'plugin__stopped__old'];
    expect(toggleAgentToolSelection(entries, 'plugin__demo__hello', true)).toEqual([
      ...entries,
      'plugin__demo__hello',
    ]);
    expect(toggleAgentToolSelection(entries, 'plugin__stopped__old', true)).toEqual(entries);
    expect(
      toggleAgentToolSelection(
        [...entries, 'plugin__demo__hello'],
        'plugin__demo__hello',
        false,
      ),
    ).toEqual(entries);
  });
});
