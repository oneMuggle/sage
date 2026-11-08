import { describe, expect, it } from 'vitest';

import {
  RULE_PACK_EXTENSION,
  RulePackParseError,
  parseRulePack,
  rulePackFileName,
  serializeRulePack,
} from '../rulePackSerialization';
import type { Rule, RuleGroup, RulePack } from '../ruleTypes';

const RULE: Rule = {
  id: 'rule-1',
  name: 'No passive voice',
  type: 'format',
  severity: 'warning',
  scope: 'body',
  description: 'avoid passive voice',
  checkMode: 'regex',
  pattern: '\\bis\\b',
  aiPrompt: undefined,
  enabled: true,
  groupId: 'group-1',
};

const GROUP: RuleGroup = {
  id: 'group-1',
  name: 'Style',
  description: 'style rules',
  rules: [RULE],
  priority: 10,
  builtin: false,
};

const PACK: RulePack = {
  name: 'house-style',
  version: '1.0',
  groups: [GROUP],
  exportedAt: '2026-11-07T10:00:00Z',
  exportedBy: 'local',
};

const WIRE_PACK = {
  name: 'house-style',
  version: '1.0',
  groups: [
    {
      id: 'group-1',
      name: 'Style',
      description: 'style rules',
      rules: [
        {
          id: 'rule-1',
          name: 'No passive voice',
          type: 'format',
          severity: 'warning',
          scope: 'body',
          description: 'avoid passive voice',
          check_mode: 'regex',
          pattern: '\\bis\\b',
          ai_prompt: null,
          enabled: true,
          group_id: 'group-1',
        },
      ],
      priority: 10,
      builtin: false,
    },
  ],
  exported_at: '2026-11-07T10:00:00Z',
  exported_by: 'local',
};

function expectParseError(text: string, code: string, field?: string) {
  let caught: unknown;
  try {
    parseRulePack(text);
  } catch (error) {
    caught = error;
  }
  expect(caught).toBeInstanceOf(RulePackParseError);
  expect((caught as RulePackParseError).code).toBe(code);
  if (field) expect((caught as RulePackParseError).field).toBe(field);
}

describe('serializeRulePack', () => {
  it('writes pretty-printed snake_case JSON identical to the import payload', () => {
    const text = serializeRulePack(PACK);

    expect(text).toContain('\n  "name"');
    expect(JSON.parse(text)).toEqual(WIRE_PACK);
  });
});

describe('parseRulePack', () => {
  it('round-trips a pack through serialize → parse', () => {
    expect(parseRulePack(serializeRulePack(PACK))).toEqual(PACK);
  });

  it('rejects malformed JSON', () => {
    expectParseError('{not json', 'invalid-json');
  });

  it('rejects a non-object root', () => {
    expectParseError('[]', 'invalid-shape');
  });

  it('rejects a missing groups array', () => {
    const payload = { ...WIRE_PACK, groups: 'nope' };
    expectParseError(JSON.stringify(payload), 'invalid-field', 'groups');
  });

  it('rejects an unknown rule type', () => {
    const payload = JSON.parse(JSON.stringify(WIRE_PACK));
    payload.groups[0].rules[0].type = 'grammar';
    expectParseError(JSON.stringify(payload), 'invalid-field', 'type');
  });

  it('rejects a rule missing check_mode', () => {
    const payload = JSON.parse(JSON.stringify(WIRE_PACK));
    delete payload.groups[0].rules[0].check_mode;
    expectParseError(JSON.stringify(payload), 'invalid-field', 'check_mode');
  });

  it('rejects a group whose rules array holds a non-object', () => {
    const payload = JSON.parse(JSON.stringify(WIRE_PACK));
    payload.groups[0].rules = ['x'];
    expectParseError(JSON.stringify(payload), 'invalid-shape', 'rules');
  });

  it('accepts null pattern and ai_prompt', () => {
    const payload = JSON.parse(JSON.stringify(WIRE_PACK));
    payload.groups[0].rules[0].pattern = null;
    payload.groups[0].rules[0].ai_prompt = null;

    const parsed = parseRulePack(JSON.stringify(payload));

    expect(parsed.groups[0].rules[0].pattern).toBeUndefined();
    expect(parsed.groups[0].rules[0].aiPrompt).toBeUndefined();
  });
});

describe('rulePackFileName', () => {
  it('appends the extension and sanitizes forbidden characters', () => {
    expect(RULE_PACK_EXTENSION).toBe('.sage-rules');
    expect(rulePackFileName('House Style / v2')).toBe('House-Style-v2.sage-rules');
    expect(rulePackFileName('   ')).toBe('rule-pack.sage-rules');
  });
});
