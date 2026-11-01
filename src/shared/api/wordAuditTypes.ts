/**
 * Word rule pack / audit / fix contracts (M2c frontend).
 *
 * Mirrors backend/office/word_rulepack_models.py. Request bodies are built
 * by officeApi and go through the Electron IPC bridge with rawBody so
 * rule params keys are never camelCase-rewritten.
 */

export type WordRuleCategory = 'page' | 'style' | 'structure' | 'content' | 'table';
export type WordRuleSeverity = 'error' | 'warning';
export type WordIssueScope = 'document' | 'section' | 'style' | 'paragraph' | 'table' | 'cell';
export type WordRulePackOrigin = 'builtin' | 'workspace';

export interface WordTextAnchor {
  part: string;
  paragraph_index: number | null;
  run_index: number | null;
  char_start: number;
  char_end: number;
  text_hash: string;
  table_index: number | null;
  row: number | null;
  col: number | null;
}

export interface WordRuleSpec {
  id: string;
  title: string;
  description?: string;
  category: WordRuleCategory;
  severity: WordRuleSeverity;
  kind: string;
  params: Record<string, unknown>;
  source?: string;
  fixable?: boolean;
  fix_hint?: string;
}

export interface WordRulePack {
  id: string;
  name: string;
  version: string;
  description?: string;
  source?: string | null;
  rules: WordRuleSpec[];
}

export interface WordRulePackSummary {
  id: string;
  name: string;
  version: string;
  description?: string;
  source?: string | null;
  origin: WordRulePackOrigin;
  rule_count: number;
}

export interface WordRulePackListResult {
  ok: boolean;
  workspace_path: string;
  packs: WordRulePackSummary[];
  warnings: Array<{ code: string; message: string }>;
}

export interface WordAuditIssue {
  rule_id: string;
  rule_pack_id: string;
  category: WordRuleCategory;
  severity: WordRuleSeverity;
  scope: WordIssueScope;
  message: string;
  expected?: string | null;
  actual?: string | null;
  fix_hint?: string;
  fixable?: boolean;
  source?: string | null;
  anchor?: WordTextAnchor | null;
}

export interface WordAuditSummary {
  rules_checked: number;
  issue_count: number;
  error_count: number;
  warning_count: number;
  paragraphs: number;
  tables: number;
  sections: number;
}

export interface WordAuditResult {
  ok: boolean;
  source_path: string;
  rule_pack_id: string;
  rule_pack_name: string;
  summary: WordAuditSummary;
  issues: WordAuditIssue[];
  warnings: Array<{ code: string; message: string }>;
}

export interface WordFixAction {
  rule_id: string;
  kind: string;
  fixed_count: number;
  message?: string;
}

export interface WordAuditFixResult {
  ok: boolean;
  source_path: string;
  output_path: string;
  overwritten: boolean;
  rule_pack_id: string;
  actions: WordFixAction[];
  fixed_count: number;
  before: WordAuditSummary;
  remaining: WordAuditResult;
  warnings: Array<{ code: string; message: string }>;
}

export interface WordAuditRequest {
  workspace_path: string;
  file_path: string;
  rulepack_id?: string;
  max_size_bytes?: number;
}

export interface WordAuditFixRequest {
  workspace_path: string;
  file_path: string;
  rulepack_id?: string;
  output_filename?: string;
  overwrite?: boolean;
  max_size_bytes?: number;
}
