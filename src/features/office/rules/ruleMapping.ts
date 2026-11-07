import type {
  WireAuditResult,
  WireExtractWarning,
  WireImportResult,
  WireRule,
  WireRuleConflict,
  WireRuleGroup,
  WireRulePack,
  WireRulePatch,
} from '../../../shared/api/types';

import type {
  Rule,
  RuleAuditResult,
  RuleConflict,
  RuleExtractWarning,
  RuleFields,
  RuleGroup,
  RuleImportResult,
  RulePack,
} from './ruleTypes';

export function ruleFromWire(wire: WireRule): Rule {
  return {
    id: wire.id,
    name: wire.name,
    type: wire.type,
    severity: wire.severity,
    scope: wire.scope,
    description: wire.description,
    checkMode: wire.check_mode,
    pattern: wire.pattern ?? undefined,
    aiPrompt: wire.ai_prompt ?? undefined,
    enabled: wire.enabled,
    groupId: wire.group_id,
  };
}

export function ruleGroupFromWire(wire: WireRuleGroup): RuleGroup {
  return {
    id: wire.id,
    name: wire.name,
    description: wire.description,
    rules: wire.rules.map(ruleFromWire),
    priority: wire.priority,
    builtin: wire.builtin,
  };
}

export function ruleGroupsFromWire(list: WireRuleGroup[]): RuleGroup[] {
  return list.map(ruleGroupFromWire);
}

/** Only keys present in `fields` are emitted, so PUT behaves as a PATCH. */
export function ruleFieldsToWire(fields: Partial<RuleFields>): WireRulePatch {
  const wire: WireRulePatch = {};
  if (fields.name !== undefined) wire.name = fields.name;
  if (fields.type !== undefined) wire.type = fields.type;
  if (fields.severity !== undefined) wire.severity = fields.severity;
  if (fields.scope !== undefined) wire.scope = fields.scope;
  if (fields.description !== undefined) wire.description = fields.description;
  if (fields.checkMode !== undefined) wire.check_mode = fields.checkMode;
  if (fields.pattern !== undefined) wire.pattern = fields.pattern;
  if (fields.aiPrompt !== undefined) wire.ai_prompt = fields.aiPrompt;
  if (fields.enabled !== undefined) wire.enabled = fields.enabled;
  return wire;
}

export function rulePackFromWire(wire: WireRulePack): RulePack {
  return {
    name: wire.name,
    version: wire.version,
    groups: ruleGroupsFromWire(wire.groups),
    exportedAt: wire.exported_at,
    exportedBy: wire.exported_by,
  };
}

export function rulePackToWire(pack: RulePack): WireRulePack {
  return {
    name: pack.name,
    version: pack.version,
    groups: pack.groups.map((group) => ({
      id: group.id,
      name: group.name,
      description: group.description,
      rules: group.rules.map((rule) => ({
        id: rule.id,
        name: rule.name,
        type: rule.type,
        severity: rule.severity,
        scope: rule.scope,
        description: rule.description,
        check_mode: rule.checkMode,
        pattern: rule.pattern ?? null,
        ai_prompt: rule.aiPrompt ?? null,
        enabled: rule.enabled,
        group_id: rule.groupId,
      })),
      priority: group.priority,
      builtin: group.builtin,
    })),
    exported_at: pack.exportedAt,
    exported_by: pack.exportedBy,
  };
}

export function conflictsFromWire(list: WireRuleConflict[]): RuleConflict[] {
  return list.map((item) => ({
    ruleIds: item.rule_ids,
    message: item.message,
    suggestion: item.suggestion,
    severity: item.severity,
  }));
}

export function extractWarningsFromWire(list: WireExtractWarning[]): RuleExtractWarning[] {
  return list.map((item) => ({ code: item.code, message: item.message }));
}

export function auditResultFromWire(wire: WireAuditResult): RuleAuditResult {
  return {
    findings: wire.findings.map((finding) => ({
      ruleId: finding.rule_id,
      ruleName: finding.rule_name,
      severity: finding.severity,
      message: finding.message,
      location: finding.location,
      suggestion: finding.suggestion,
    })),
    errorCount: wire.error_count,
    warningCount: wire.warning_count,
    infoCount: wire.info_count,
  };
}

export function importResultFromWire(wire: WireImportResult): RuleImportResult {
  return {
    groups: wire.groups,
    importedRules: wire.imported_rules,
  };
}
