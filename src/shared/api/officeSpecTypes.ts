/**
 * 格式规范书库（M2.5）与 AI 合并审校（M3）的前端契约。
 *
 * 镜像 backend/office/spec_models.py 与 backend/office/ai_review_models.py。
 * 字段名保持后端 snake_case：请求体经 Electron IPC 桥的 rawBody 透传，
 * 不会被通用 camelCase 转换改写。规则包本体复用 wordAuditTypes.WordRulePack。
 */

import type { WordRulePack } from './wordAuditTypes';

// ── 规范书库（M2.5） ────────────────────────────────────────────────

export interface OfficeSpecDocument {
  id: string;
  workspace_path: string;
  name: string;
  source_file_path: string | null;
  source_content_hash: string | null;
  rulepack_id: string;
  is_default: boolean;
  created_at: number;
  updated_at: number;
}

export interface OfficeSpecListResult {
  ok: boolean;
  workspace_path: string;
  specs: OfficeSpecDocument[];
}

export interface OfficeSpecDetailResult {
  ok: boolean;
  spec: OfficeSpecDocument;
  rulepack: WordRulePack | null;
}

export interface OfficeSpecSaveResult {
  ok: boolean;
  spec: OfficeSpecDocument;
  rulepack: WordRulePack | null;
}

export interface OfficeSpecBindingResult {
  ok: boolean;
  doc_id: string;
  spec_id: string | null;
  /** 解析后的生效规范书（显式 > 文档绑定 > 工作区默认）。 */
  effective_spec: OfficeSpecDocument | null;
}

export interface OfficeSpecCreateRequest {
  workspace_path: string;
  name: string;
  /** 二选一：直接提交草稿规则包，或引用已存在的规则包 id。 */
  pack?: WordRulePack;
  rulepack_id?: string;
  source_file_path?: string | null;
  source_content_hash?: string | null;
  is_default?: boolean;
}

export interface OfficeSpecUpdateRequest {
  workspace_path: string;
  name?: string;
  pack?: WordRulePack;
  source_file_path?: string | null;
  source_content_hash?: string | null;
}

export interface OfficeSpecExtractRequest {
  workspace_path: string;
  file_path: string;
  pack_id?: string;
  pack_name?: string;
  use_llm?: boolean;
  max_size_bytes?: number;
}

// ── AI 合并审校（M3） ───────────────────────────────────────────────

export type AiReviewSourceKind = 'spec' | 'llm' | 'builtin';
export type AiReviewSeverity = 'error' | 'warning' | 'info';
export type AiReviewScope = 'full' | 'selection' | 'section';

export interface AiReviewSource {
  kind: AiReviewSourceKind;
  spec_id: string | null;
  spec_name: string | null;
  rule_id: string | null;
  rule_pack_id: string | null;
}

export interface AiReviewLocation {
  paragraph_index: number | null;
  paragraph_text: string | null;
}

export interface AiReviewIssue {
  id: string;
  severity: AiReviewSeverity;
  category: string;
  message: string;
  suggestion: string;
  rationale: string;
  expected: string | null;
  actual: string | null;
  fixable: boolean;
  location: AiReviewLocation | null;
  source: AiReviewSource;
}

export interface AiReviewSummary {
  rules_checked: number;
  issue_count: number;
  error_count: number;
  warning_count: number;
  info_count: number;
  spec_issue_count: number;
  llm_issue_count: number;
  duration_ms: number;
  model: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
}

export interface AiReviewWarning {
  code: string;
  message?: string;
  [key: string]: string | undefined;
}

export interface AiReviewResult {
  ok: boolean;
  doc_id: string | null;
  file_path: string;
  scope: AiReviewScope;
  spec_id: string | null;
  spec_name: string | null;
  summary: AiReviewSummary;
  issues: AiReviewIssue[];
  warnings: AiReviewWarning[];
}

export interface AiReviewHistoryItem {
  id: number;
  doc_id: string;
  spec_id: string | null;
  model: string | null;
  scope: string;
  issue_count: number;
  summary: Record<string, unknown> | null;
  duration_ms: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  created_at: number;
}

export interface AiReviewHistoryResult {
  ok: boolean;
  doc_id: string;
  runs: AiReviewHistoryItem[];
}

export interface AiReviewRequest {
  workspace_path: string;
  file_path: string;
  doc_id?: string;
  spec_id?: string;
  scope?: AiReviewScope;
  use_llm?: boolean;
  max_issues?: number;
  max_size_bytes?: number;
}

/** POST /office/ai/revise request — apply selected issues as tracked revisions. */
export interface AiReviseRequest {
  workspace_path: string;
  file_path: string;
  doc_id?: string;
  issues: AiReviewIssue[];
  output_filename?: string;
  author?: string;
  add_comments?: boolean;
}

/** POST /office/ai/revise result. */
export interface AiReviseResult {
  ok: boolean;
  doc_id: string | null;
  snapshot_path: string | null;
  source_path: string;
  output_path: string;
  overwritten: boolean;
  planned: number;
  applied: number;
  skipped: number;
  changes: Array<{
    rule_id: string | null;
    find: string;
    replace: string;
    comment: string;
    applied: boolean;
    reason: string;
  }>;
  warnings: Array<Record<string, string>>;
}
