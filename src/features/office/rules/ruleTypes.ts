/**
 * Rules-workspace design types (camelCase), mirroring the redesign spec §3.5.
 *
 * Transport shapes are snake_case and live in
 * src/shared/api/types/officeRulesTypes.ts. ruleMapping.ts is the only module
 * that converts between the two.
 */

export const RULE_TYPES = ['format', 'terminology', 'citation', 'structure', 'custom'] as const;
export const RULE_SEVERITIES = ['error', 'warning', 'info'] as const;
export const RULE_SCOPES = ['full', 'heading', 'body', 'table', 'caption'] as const;
export const RULE_CHECK_MODES = ['regex', 'ai'] as const;

export type RuleType = (typeof RULE_TYPES)[number];
export type RuleSeverity = (typeof RULE_SEVERITIES)[number];
export type RuleScope = (typeof RULE_SCOPES)[number];
export type RuleCheckMode = (typeof RULE_CHECK_MODES)[number];

export interface Rule {
  id: string;
  name: string;
  type: RuleType;
  severity: RuleSeverity;
  scope: RuleScope;
  description: string;
  checkMode: RuleCheckMode;
  pattern?: string;
  aiPrompt?: string;
  enabled: boolean;
  groupId: string;
}

/** Editable subset of a rule; `id` and `groupId` are owned by the container. */
export type RuleFields = Omit<Rule, 'id' | 'groupId'>;

export interface RuleGroup {
  id: string;
  name: string;
  description: string;
  rules: Rule[];
  priority: number;
  builtin: boolean;
}

export interface RulePack {
  name: string;
  version: string;
  groups: RuleGroup[];
  exportedAt: string;
  exportedBy: string;
}

export interface RuleConflict {
  ruleIds: string[];
  message: string;
  suggestion: string;
  severity: RuleSeverity;
}

export interface RuleAuditFinding {
  ruleId: string;
  ruleName: string;
  severity: RuleSeverity;
  message: string;
  location: string;
  suggestion: string;
}

export interface RuleAuditResult {
  findings: RuleAuditFinding[];
  errorCount: number;
  warningCount: number;
  infoCount: number;
}

export interface RuleExtractWarning {
  code: string;
  message: string;
}

export interface RuleImportResult {
  /** Number of groups created by the import. */
  groups: number;
  importedRules: number;
}
