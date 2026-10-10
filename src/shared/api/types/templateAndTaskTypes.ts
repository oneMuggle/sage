import type { OfficeDocumentSummary, ReferenceSpec } from '../types';

export interface OfficeUpdateOp {
  op: string;
  [key: string]: unknown;
}

/** Request of POST /office/update/preview — exactly one of file_path / doc_id. */
export interface OfficeUpdatePreviewRequest {
  workspace_path: string;
  file_path?: string;
  doc_id?: string;
  ops: OfficeUpdateOp[];
}

/** One human-readable change entry in a preview (backend DiffPreviewChange). */
export interface OfficeDiffPreviewChange {
  op: string;
  /** Where the change lands: 'Sheet!A1', 'slide[2]', 'table[0]'… */
  target?: string | null;
  /** Content before the op (snippet). */
  before?: string | null;
  /** Content after the op (snippet). */
  after?: string | null;
  /** One-line description when before/after don't tell the story. */
  summary?: string | null;
}

/** Result of POST /office/update/preview (backend DiffPreviewResult). */
export interface OfficeUpdatePreviewResult {
  /** False when applying the ops to the preview copy failed. */
  ok: boolean;
  changes: OfficeDiffPreviewChange[];
  /** True when the change list was capped server-side (MAX_CHANGES=200). */
  truncated: boolean;
  /** Why the real update would fail (set when ok=false). */
  error?: string | null;
  /**
   * F1: content revision (`sha256:…`) of the file this preview was computed
   * from. Pass it back as `expected_revision` on apply so a file that
   * changed in between is rejected (409) instead of silently overwritten.
   * Optional — older backends omit it.
   */
  source_revision?: string | null;
  /** Stable digest of the previewed op batch. */
  ops_hash?: string | null;
  /** Opaque id correlating this preview with its apply. */
  preview_id?: string | null;
}

// ──────────────────────────────────────────────────────────────────────
// Update apply (Office parity round 2 — R1 close the edit-preview loop)
// Route: POST /api/v1/office/doc/{doc_id}/update, body {ops} (same op
// dicts the preview route takes). Errors: unknown doc → 404 JSON
// {error_type, message, file_path}; invalid ops → 422 same shape (both
// surface as thrown errors via handleApiError, never as ok=false).
// ──────────────────────────────────────────────────────────────────────

/** Request of POST /office/doc/{doc_id}/update. */
export interface OfficeDocUpdateRequest {
  doc_id: string;
  ops: OfficeUpdateOp[];
  /** F1: the revision the user previewed; mismatch → 409, file untouched. */
  expected_revision?: string | null;
  /** F1: retry token — a repeated apply replays instead of applying twice. */
  idempotency_key?: string | null;
}

/**
 * Post-apply self-check report (backend re-reads the document and
 * verifies the ops landed). `summary` is an opaque object — the UI
 * renders the counts line from the updated OfficeDocumentSummary instead.
 */
export interface OfficeUpdateSelfCheck {
  ok: boolean;
  summary?: Record<string, unknown> | null;
  error?: string | null;
}

/** Response of POST /office/doc/{doc_id}/update (backend OfficeDocUpdateResult). */
export interface OfficeDocUpdateResponse {
  ok: boolean;
  /** Post-update document summary (status='edited', refreshed updated_at). */
  summary: OfficeDocumentSummary;
  self_check: OfficeUpdateSelfCheck;
  /** Content revision of the saved file — chain it into the next edit. */
  revision?: string | null;
  /** Revision the ops were applied to. */
  previous_revision?: string | null;
  /** True when this response replays an earlier apply with the same key. */
  idempotent_replay?: boolean;
  /**
   * Per-op outcomes from the backend editor (backend.office.edit) —
   * `[{op, ok, ...}]`. Not rendered today; typed so the contract is
   * visible at the call site.
   */
  results?: Record<string, unknown>[];
}

/**
 * Response of GET /office/doc/{doc_id}/revision (F1/F2 read side) — the
 * content identity the preview caches key on.
 */
export interface OfficeDocRevisionResponse {
  doc_id: string;
  /** `sha256:…` of the managed file's current bytes. */
  revision: string;
  size_bytes: number;
  mtime_ms: number;
}

/** Request of POST /office/export-pdf. */
export interface OfficeExportPdfRequest {
  /** P7: 进度追踪任务 id（前端 uuid；GET /office/progress/{id} 轮询） */
  task_id?: string;
  workspace_path: string;
  file_path: string;
}

/**
 * Result of POST /office/export-pdf (backend ExportPdfResult). `method`
 * is null whenever ok=false; `output_path` is populated only on success
 * (`<stem>.pdf` next to the source inside the workspace).
 */
export interface OfficeExportPdfResult {
  ok: boolean;
  method?: 'libreoffice' | 'word_com' | null;
  output_path?: string | null;
  error?: string | null;
}

// ──────────────────────────────────────────────────────────────────────
// Office display round A — P6 capability probe + P1 high-fidelity preview
// Backend counterpart: backend/office/capabilities.py (OfficeCapabilities)
// and backend/office/pdf_preview.py (PdfPreviewResult).
// ──────────────────────────────────────────────────────────────────────

/** Result of GET /office/capabilities (backend OfficeCapabilities). */
export interface OfficeCapabilities {
  platform: string;
  soffice_available: boolean;
  soffice_path?: string | null;
  word_com_available: boolean;
  pdf_export_available: boolean;
  pillow_available: boolean;
  formulas_available: boolean;
  /** P4-A (office-p4a): OCR 兜底可用（pytesseract 已装且 tesseract 在 PATH）。 */
  ocr_available: boolean;
  /** Static discovery only; missing fields indicate a legacy backend. */
  pdf_export_formats?: Array<'docx' | 'xlsx' | 'pptx'>;
  conversion_probe_status?: 'detected' | 'unavailable';
}

/**
 * Result of POST /office/pdf-preview (backend PdfPreviewResult).
 * `data_url` is a data:application/pdf;base64 URL rendered by the
 * embedded Chromium PDF viewer; `cached=true` means no converter ran.
 */
export interface OfficePdfPreviewResult {
  ok: boolean;
  data_url?: string | null;
  cached?: boolean;
  error?: string | null;
}

/**
 * Round C P5: POST /office/templates/thumbnail — first-page PNG thumbnail
 * of a library template (builtin or workspace). Failures fold to ok=false
 * and the picker degrades silently (thumbnails are decorative).
 */
export interface OfficeTemplateThumbnailResult {
  ok: boolean;
  /** data:image/png;base64,… */
  data_url?: string | null;
  cached?: boolean;
  error?: string | null;
}

// ──────────────────────────────────────────────────────────────────────
// Document template library (Office parity batch 3, item 3.2 — 从模板创建;
// round 3 N2 extends it to excel/ppt). Backend counterpart: GET
// /office/templates + POST /office/templates/instantiate in
// backend/api/office_routes.py. Placeholder element shape follows the
// list-endpoint contract (name/type/description) — narrower than the
// analysis model `TemplatePlaceholder` (backend/office/models.py), which
// carries location/index fields that the picker UI never needs.
// ──────────────────────────────────────────────────────────────────────

/** Placeholder kind (backend `TemplatePlaceholderType`). */
export type OfficeTemplatePlaceholderType = 'text' | 'image' | 'table' | 'date' | 'rich_text';

/** Where a template comes from (backend `source` discriminator). */
export type OfficeTemplateSource = 'builtin' | 'workspace';

/** One placeholder in a template (GET /office/templates element). */
export interface OfficeTemplatePlaceholder {
  name: string;
  type: OfficeTemplatePlaceholderType;
  description?: string;
}

/**
 * One template entry. `id` is the instantiate key for builtin templates;
 * workspace templates resolve by filename (`workspace_template`), with
 * `id` mirroring the filename stem for list rendering.
 *
 * Round 3 N2: `doc_type` was widened from the batch-3 `'word'`-only
 * literal to the OOXML trio — the backend list endpoint now also yields
 * excel/ppt builtin + workspace templates and instantiate persists the
 * matching document row for all three.
 */
export interface OfficeTemplateMeta {
  id: string;
  name: string;
  description?: string;
  doc_type: 'word' | 'excel' | 'ppt';
  placeholders: OfficeTemplatePlaceholder[];
  source: OfficeTemplateSource;
  /** Workspace templates only — the source OOXML filename inside the workspace. */
  filename?: string;
}

/** Response of GET /office/templates?workspace_path=… */
export interface OfficeTemplateListResponse {
  templates: OfficeTemplateMeta[];
}

/**
 * Request of POST /office/templates/instantiate. Exactly one of
 * `template_id` (builtin) / `workspace_template` (filename) is sent.
 *
 * NOTE: `data` / `images` keys are template placeholder names — user
 * data, not JS identifiers — so the IPC route is declared `rawBody` and
 * the camelToSnake translation never touches them (same reasoning as
 * mcp_server_add's env map).
 */
export interface OfficeTemplateInstantiateRequest {
  /** P7: 进度追踪任务 id（前端 uuid；GET /office/progress/{id} 轮询） */
  task_id?: string;
  workspace_path: string;
  template_id?: string;
  workspace_template?: string;
  filename: string;
  data: Record<string, string>;
  images?: Record<string, string>;
}

/**
 * Result of POST /office/templates/instantiate — same shape for all
 * doc types (word: backend `WordTemplateFillResult`,
 * backend/office/models.py:551-557, which already carries `output_path`;
 * round 3 N2: excel/ppt instantiate reuses the identical response shape).
 * The backend persists a document row, so the result shows up in the
 * document list after a refresh.
 */
export interface OfficeTemplateInstantiateResult {
  output_path: string;
  filename: string;
  file_size_bytes: number;
  filled_count: number;
  /** Placeholder names the template still contains after the fill. */
  unfilled_placeholders: string[];
}

// ==================== Journal template types (Task 7, 2026-09-10) ====================

/**
 * Journal template subsystem (Task 7, 2026-09-10).
 * Mirrors backend/office/journal/models.py: JournalSpec, JournalViolation, etc.
 */

/** Font family descriptor — mirrors backend FontFamily Pydantic model. */
export interface FontFamily {
  family: string;
  ascii_family?: string;
  eastasia?: string;
}

/** Single chapter heading extracted from a .docx template. */
export interface JournalSpecHeading {
  keyword: string;
  level: number;
  expected_pt: number;
}

/** Parsed journal template — body font/size/spacing/margins + heading roster + citation style. */
export interface JournalSpec {
  spec_id: string;
  template_sha256: string;
  template_filename: string;
  font_body: FontFamily;
  font_heading: FontFamily;
  body_pt: number;
  heading_pt: number;
  line_spacing: number;
  margins_cm: number;
  headings: JournalSpecHeading[];
  citation_style: string;
  page_size: string;
  extra: Record<string, unknown>;
}

/** Summary view of a JournalSpec for list endpoints — headings are keyword strings only. */
export interface JournalSpecSummary {
  spec_id: string;
  template_sha256: string;
  template_filename: string;
  headings: string[];
  body_pt: number;
}

/** One rule violation emitted by the 6-rule validator. */
export interface JournalViolation {
  rule_id: string;
  severity: 'error' | 'warning' | 'info';
  message: string;
  location: string;
  suggestion: string;
}

/** POST /api/v1/office/journal/parse-template response. */
export interface JournalParseTemplateResponse {
  spec: JournalSpec;
  cached: boolean;
}

/** GET /api/v1/office/journal/specs response. */
export interface JournalListSpecsResponse {
  specs: JournalSpecSummary[];
}

/** GET /api/v1/office/journal/specs/{spec_id} response. */
export interface JournalGetSpecResponse {
  spec: JournalSpec;
}

/** POST /api/v1/office/journal/validate response. */
export interface JournalValidateResponse {
  spec_id: string;
  file_path: string;
  violations: JournalViolation[];
  error_count: number;
  warning_count: number;
}

/** One section's text, keyed by the heading keyword. */
export interface JournalContentSection {
  [keyword: string]: string;
}

/** POST /api/v1/office/journal/fill-from-content request body. */
export interface JournalFillFromContentRequest {
  spec_id: string;
  workspace_path: string;
  content: {
    title: string;
    abstract: string;
    sections: JournalContentSection;
    references: string[];
    citations?: string[];
    // Round 21：结构化文献（fill 时用引用引擎格式化，优先于 references）
    structured_references?: ReferenceSpec[];
    citation_style?: 'gbt7714' | 'apa';
  };
  output_filename: string;
}

/** POST /api/v1/office/journal/fill-from-content response. */
export interface JournalFillFromContentResponse {
  spec_id: string;
  output_path: string;
  gen_id: string;
  bytes_written: number;
}

// ============================================================================
// Todo subsystem (personal todolist)
//
// NOTE: `TodoStatus` and `TodoItem` already exist earlier in this file
// (agent self-maintained checklist snapshots, 3-state). They are a different
// concept — do NOT redefine, rename, or reuse them here.
// ============================================================================

export type TodoPriority = 'high' | 'medium' | 'low';

export type TodoItemStatus = 'pending' | 'in_progress' | 'completed' | 'cancelled';

export type TodoUrgency = 'critical' | 'urgent' | 'normal';

export interface Todo {
  id: number;
  title: string;
  description?: string | null;
  status: TodoItemStatus;
  priority: TodoPriority;
  effective_urgency?: TodoUrgency | null;
  due_at?: string | null;
  completed_at?: string | null;
  project_tag?: string | null;
  project_id?: string | null;
  is_recurring: boolean;
  recurrence_rule?: string | null;
  parent_id?: number | null;
  created_at: string;
  updated_at: string;
}

export interface CreateTodoInput {
  title: string;
  description?: string;
  due_at?: string;
  priority?: TodoPriority;
  project_tag?: string;
  recurrence_rule?: string;
}

export interface UpdateTodoInput {
  title?: string;
  description?: string;
  due_at?: string;
  priority?: TodoPriority;
  project_tag?: string;
  status?: 'pending' | 'in_progress' | 'cancelled';
  recurrence_rule?: string;
}

export interface TodoSummary {
  overdue: Todo[];
  today: Todo[];
  upcoming: Todo[];
  high_priority: Todo[];
  total_pending: number;
  total_completed_today: number;
}

export interface TodoStats {
  total: number;
  by_status: Record<string, number>;
  by_priority: Record<string, number>;
  overdue: number;
  due_today: number;
  completed_today: number;
}

export interface TodoListResponse {
  items: Todo[];
  total: number;
  limit: number;
  offset: number;
}

export interface TodoListParams {
  status?: string;
  project_tag?: string;
  priority?: TodoPriority;
  include_completed?: boolean;
  sort_by?: 'due_at' | 'priority' | 'created_at';
  sort_order?: 'asc' | 'desc';
  limit?: number;
  offset?: number;
}
