/**
 * `.sage-rules` files store the wire (snake_case) shape so an exported file is
 * itself a valid POST /api/v1/rules/import payload.
 */

import type { WireRule, WireRuleGroup, WireRulePack } from '../../../shared/api/types';

import { rulePackFromWire, rulePackToWire } from './ruleMapping';
import type { RulePack } from './ruleTypes';
import { RULE_CHECK_MODES, RULE_SCOPES, RULE_SEVERITIES, RULE_TYPES } from './ruleTypes';

export const RULE_PACK_EXTENSION = '.sage-rules';

export type RulePackParseErrorCode = 'invalid-json' | 'invalid-shape' | 'invalid-field';

export class RulePackParseError extends Error {
  readonly code: RulePackParseErrorCode;
  readonly field?: string;

  constructor(code: RulePackParseErrorCode, message: string, field?: string) {
    super(message);
    this.name = 'RulePackParseError';
    this.code = code;
    this.field = field;
  }
}

export function serializeRulePack(pack: RulePack): string {
  return JSON.stringify(rulePackToWire(pack), null, 2);
}

export function parseRulePack(text: string): RulePack {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new RulePackParseError('invalid-json', '规则包不是合法的 JSON');
  }
  if (!isRecord(parsed)) {
    throw new RulePackParseError('invalid-shape', '规则包必须是 JSON 对象');
  }
  return rulePackFromWire(parsePack(parsed));
}

export function rulePackFileName(name: string): string {
  const slug = name
    .trim()
    .replace(/[\s\\/:*?"<>|]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return `${slug || 'rule-pack'}${RULE_PACK_EXTENSION}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function fail(code: RulePackParseErrorCode, field: string, message: string): never {
  throw new RulePackParseError(code, message, field);
}

function readString(source: Record<string, unknown>, key: string): string {
  const value = source[key];
  if (typeof value !== 'string') fail('invalid-field', key, `${key} 必须是字符串`);
  return value;
}

function readOptionalString(
  source: Record<string, unknown>,
  key: string,
): string | null | undefined {
  const value = source[key];
  if (value === undefined || value === null) return value;
  if (typeof value !== 'string') fail('invalid-field', key, `${key} 必须是字符串或 null`);
  return value;
}

function readBoolean(source: Record<string, unknown>, key: string): boolean {
  const value = source[key];
  if (typeof value !== 'boolean') fail('invalid-field', key, `${key} 必须是布尔值`);
  return value;
}

function readNumber(source: Record<string, unknown>, key: string): number {
  const value = source[key];
  if (typeof value !== 'number' || Number.isNaN(value)) {
    fail('invalid-field', key, `${key} 必须是数字`);
  }
  return value;
}

function readOneOf<T extends string>(
  source: Record<string, unknown>,
  key: string,
  allowed: readonly T[],
): T {
  const value = source[key];
  if (typeof value !== 'string' || !allowed.includes(value as T)) {
    fail('invalid-field', key, `${key} 必须是 ${allowed.join(' / ')} 之一`);
  }
  return value as T;
}

function readRecords(
  source: Record<string, unknown>,
  key: string,
  label: string,
): Record<string, unknown>[] {
  const value = source[key];
  if (!Array.isArray(value)) fail('invalid-field', key, `${key} 必须是数组`);
  return value.map((item, index) => {
    if (!isRecord(item)) {
      fail('invalid-shape', key, `${label}[${index}] 必须是对象`);
    }
    return item;
  });
}

function parseRule(raw: Record<string, unknown>): WireRule {
  return {
    id: readString(raw, 'id'),
    name: readString(raw, 'name'),
    type: readOneOf(raw, 'type', RULE_TYPES),
    severity: readOneOf(raw, 'severity', RULE_SEVERITIES),
    scope: readOneOf(raw, 'scope', RULE_SCOPES),
    description: readString(raw, 'description'),
    check_mode: readOneOf(raw, 'check_mode', RULE_CHECK_MODES),
    pattern: readOptionalString(raw, 'pattern'),
    ai_prompt: readOptionalString(raw, 'ai_prompt'),
    enabled: readBoolean(raw, 'enabled'),
    group_id: readString(raw, 'group_id'),
  };
}

function parseGroup(raw: Record<string, unknown>): WireRuleGroup {
  return {
    id: readString(raw, 'id'),
    name: readString(raw, 'name'),
    description: readString(raw, 'description'),
    rules: readRecords(raw, 'rules', 'rules').map(parseRule),
    priority: readNumber(raw, 'priority'),
    builtin: readBoolean(raw, 'builtin'),
  };
}

function parsePack(raw: Record<string, unknown>): WireRulePack {
  return {
    name: readString(raw, 'name'),
    version: readString(raw, 'version'),
    groups: readRecords(raw, 'groups', 'groups').map(parseGroup),
    exported_at: readString(raw, 'exported_at'),
    exported_by: readString(raw, 'exported_by'),
  };
}
