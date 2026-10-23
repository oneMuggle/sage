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

describe('EditAgentForm running plugin tool helpers (R94)', () => {
  it('recognizes only the two legal plugin wildcard forms as coverage', () => {
    const toolName = 'plugin__demo__hello';
    expect(findPluginToolWildcardCover(['plugin__*'], toolName)).toBe('plugin__*');
    expect(findPluginToolWildcardCover(['plugin__demo__*'], toolName)).toBe(
      'plugin__demo__*',
    );
    expect(findPluginToolWildcardCover(['plugin__other__*'], toolName)).toBeUndefined();
    expect(findPluginToolWildcardCover(['plugin__*'], 'read_file')).toBeUndefined();
    expect(findPluginToolWildcardCover(['plugin__demo*'], toolName)).toBeUndefined();
    expect(findPluginToolWildcardCover(['plugin__demo__he*'], toolName)).toBeUndefined();
    expect(
      findPluginToolWildcardCover(
        ['plugin__demo__*'],
        'plugin__demo__nested__tool',
      ),
    ).toBeUndefined();
    expect(
      findPluginToolWildcardCover(
        ['plugin__de__mo__*'],
        'plugin__de__mo__tool',
      ),
    ).toBeUndefined();
  });

  it('separates exact selection from wildcard-only coverage', () => {
    expect(
      pluginToolSelectionState(['plugin__demo__*'], 'plugin__demo__hello'),
    ).toEqual({
      selected: true,
      exact: false,
      coveredBy: 'plugin__demo__*',
    });
    expect(
      pluginToolSelectionState(
        ['plugin__demo__hello', 'plugin__demo__*'],
        'plugin__demo__hello',
      ),
    ).toEqual({
      selected: true,
      exact: true,
      coveredBy: 'plugin__demo__*',
    });
    expect(pluginToolSelectionState([], 'plugin__demo__hello')).toEqual({
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
