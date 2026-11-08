/**
 * Wire types for /api/v1/rules (snake_case). Convert with
 * src/features/office/rules/ruleMapping.ts — never camelCase these by hand.
 */

export type WireRuleType = 'format' | 'terminology' | 'citation' | 'structure' | 'custom';
export type WireRuleSeverity = 'error' | 'warning' | 'info';
export type WireRuleScope = 'full' | 'heading' | 'body' | 'table' | 'caption';
export type WireRuleCheckMode = 'regex' | 'ai';

export interface WireRule {
  id: string;
  name: string;
  type: WireRuleType;
  severity: WireRuleSeverity;
  scope: WireRuleScope;
  description: string;
  check_mode: WireRuleCheckMode;
  pattern?: string | null;
  ai_prompt?: string | null;
  enabled: boolean;
  group_id: string;
}

export interface WireRuleGroup {
  id: string;
  name: string;
  description: string;
  rules: WireRule[];
  priority: number;
  builtin: boolean;
}

export interface WireRulePack {
  name: string;
  version: string;
  groups: WireRuleGroup[];
  exported_at: string;
  exported_by: string;
}

/** Body of POST /rules/groups/{id}/rules. */
export interface WireRuleInput {
  name: string;
  type: WireRuleType;
  severity: WireRuleSeverity;
  scope: WireRuleScope;
  description?: string;
  check_mode: WireRuleCheckMode;
  pattern?: string | null;
  ai_prompt?: string | null;
  enabled?: boolean;
}

/** Body of PUT /rules/rules/{id}. */
export type WireRulePatch = Partial<WireRuleInput>;

export interface WireGroupInput {
  name: string;
  description?: string;
  priority?: number;
}

/** Body of PUT /rules/groups/{id}. */
export type WireGroupPatch = Partial<WireGroupInput>;

/** Both DELETE routes return this JSON body (the relay cannot parse 204). */
export interface WireDeleteResult {
  deleted: boolean;
  id: string;
}

export interface WireExtractRequest {
  workspace_path: string;
  file_path: string;
  file_type?: string;
  use_llm?: boolean;
  max_size_bytes?: number;
}

export interface WireExtractWarning {
  code: string;
  message: string;
}

export interface WireExtractResult {
  rules: WireRule[];
  warnings: WireExtractWarning[];
}

export interface WireRuleConflict {
  rule_ids: string[];
  message: string;
  suggestion: string;
  severity: WireRuleSeverity;
}

export interface WireConflictResult {
  conflicts: WireRuleConflict[];
}

export interface WireExportRequest {
  group_ids: string[];
  name: string;
  version?: string;
}

export interface WireImportResult {
  /** Number of groups created by the import (backend `ImportResponse.groups`). */
  groups: number;
  imported_rules: number;
}

export interface WireAuditRequest {
  workspace_path: string;
  file_path: string;
  rule_ids: string[];
  max_size_bytes?: number;
}

export interface WireAuditFinding {
  rule_id: string;
  rule_name: string;
  severity: WireRuleSeverity;
  message: string;
  location: string;
  suggestion: string;
}

export interface WireAuditResult {
  findings: WireAuditFinding[];
  error_count: number;
  warning_count: number;
  info_count: number;
}
