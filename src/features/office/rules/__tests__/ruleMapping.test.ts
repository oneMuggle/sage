import { describe, expect, it } from 'vitest';

import type { WireRule, WireRuleGroup, WireRulePack } from '../../../../shared/api/types';
import {
  auditResultFromWire,
  conflictsFromWire,
  ruleFieldsToWire,
  ruleFromWire,
  ruleGroupFromWire,
  rulePackFromWire,
  rulePackToWire,
} from '../ruleMapping';
import type { Rule, RuleGroup, RulePack } from '../ruleTypes';

const WIRE_RULE: WireRule = {
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
};

const WIRE_GROUP: WireRuleGroup = {
  id: 'group-1',
  name: 'Style',
  description: 'style rules',
  rules: [WIRE_RULE],
  priority: 10,
  builtin: false,
};

const DESIGN_RULE: Rule = {
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

const DESIGN_GROUP: RuleGroup = {
  id: 'group-1',
  name: 'Style',
  description: 'style rules',
  rules: [DESIGN_RULE],
  priority: 10,
  builtin: false,
};

const WIRE_PACK: WireRulePack = {
  name: 'house-style',
  version: '1.0',
  groups: [WIRE_GROUP],
  exported_at: '2026-11-07T10:00:00Z',
  exported_by: 'local',
};

const DESIGN_PACK: RulePack = {
  name: 'house-style',
  version: '1.0',
  groups: [DESIGN_GROUP],
  exportedAt: '2026-11-07T10:00:00Z',
  exportedBy: 'local',
};

describe('ruleMapping', () => {
  it('converts a wire rule to a design rule (snake_case → camelCase, null → undefined)', () => {
    expect(ruleFromWire(WIRE_RULE)).toEqual(DESIGN_RULE);
  });

  it('converts a wire group and its nested rules', () => {
    expect(ruleGroupFromWire(WIRE_GROUP)).toEqual(DESIGN_GROUP);
  });

  it('converts design fields to a wire patch and omits keys that were not provided', () => {
    expect(ruleFieldsToWire({ checkMode: 'ai', aiPrompt: 'check tone', enabled: false })).toEqual({
      check_mode: 'ai',
      ai_prompt: 'check tone',
      enabled: false,
    });
  });

  it('converts a wire pack to a design pack', () => {
    expect(rulePackFromWire(WIRE_PACK)).toEqual(DESIGN_PACK);
  });

  it('round-trips a design pack through the wire format', () => {
    expect(rulePackFromWire(rulePackToWire(DESIGN_PACK))).toEqual(DESIGN_PACK);
  });

  it('maps conflicts and audit results', () => {
    expect(
      conflictsFromWire([
        {
          rule_ids: ['rule-1', 'rule-2'],
          message: 'overlap',
          suggestion: 'keep one',
          severity: 'warning',
        },
      ]),
    ).toEqual([
      { ruleIds: ['rule-1', 'rule-2'], message: 'overlap', suggestion: 'keep one', severity: 'warning' },
    ]);

    expect(
      auditResultFromWire({
        findings: [
          {
            rule_id: 'rule-1',
            rule_name: 'No passive voice',
            severity: 'warning',
            message: 'passive voice',
            location: '第 3 段',
            suggestion: 'rewrite',
          },
        ],
        error_count: 0,
        warning_count: 1,
        info_count: 0,
      }),
    ).toEqual({
      findings: [
        {
          ruleId: 'rule-1',
          ruleName: 'No passive voice',
          severity: 'warning',
          message: 'passive voice',
          location: '第 3 段',
          suggestion: 'rewrite',
        },
      ],
      errorCount: 0,
      warningCount: 1,
      infoCount: 0,
    });
  });
});
