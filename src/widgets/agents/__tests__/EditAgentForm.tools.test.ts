import { describe, expect, it } from 'vitest';

import { formatAgentToolsInput, parseAgentToolsInput } from '../EditAgentForm';

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
