export * from './types/chatAndEventTypes';
export * from './types/domainEntityTypes';
export * from './types/templateAndTaskTypes';

export type OfficeDocType = 'ppt' | 'word' | 'excel' | 'pdf';

export type OfficeDocStatus = 'parsed' | 'generated' | 'edited';

export interface OfficeDocumentMetadata {
  page_count?: number;
  sheet_count?: number;
  paragraph_count?: number;
  table_count?: number;
  file_size_bytes: number;
}

export interface OfficeDocumentSummary {
  id: string;
  /**
   * Binding's canonical absolute workspace directory.
   * Backend strips this in `_serialize_summary` for LLM tool outputs
   * (backend/office/tool_service.py:72-81); present in read-result summaries
   * (OfficeExcelReadResult.summary etc.) which bypass that redactor.
   * Marked optional so callers handle both shapes.
   */
  workspace_path?: string;
  doc_type: OfficeDocType;
  original_filename: string | null;
  generated_filename: string;
  status: OfficeDocStatus;
  created_at: number;
  updated_at: number;
  metadata: OfficeDocumentMetadata;
  /**
   * Source document id when this row was produced by an edit/copy/derive
   * operation; null for fresh reads and from-scratch generations.
   * Backend field: backend/office/models.py:93-99.
   */
  derived_from: string | null;
  /**
   * Unix timestamp (ms) when the row was soft-deleted via archive.
   * Non-null rows are hidden from `list_documents(include_archived=False)`.
   * Backend field: backend/office/models.py:100-106.
   */
  archived_at: number | null;
}

export interface OfficePptSlideContent {
  index: number;
  title: string | null;
  text_blocks: string[];
  table_count: number;
  image_count: number;
  notes: string | null;
}

export interface OfficePptReadResult {
  summary: OfficeDocumentSummary;
  slides: OfficePptSlideContent[];
  // Round 52：core properties 回读（无属性为 null）
  metadata?: WordMetadataSpec | null;
}

export interface OfficeWordParagraphContent {
  style: string;
  text: string;
  level: number;
}

export interface OfficeWordTableContent {
  rows: string[][];
}

export interface WordHeaderFooterContent {
  // Round 15：read_docx 页眉/页脚提取（section 为 1-based 节号）。
  // Backend counterpart: WordHeaderFooterContent in backend/office/models.py。
  section: number;
  header_text: string;
  footer_text: string;
  has_page_number_field: boolean;
}

export interface OfficeWordReadResult {
  summary: OfficeDocumentSummary;
  paragraphs: OfficeWordParagraphContent[];
  tables: OfficeWordTableContent[];
  images: number;
  // Round C P4: typed — the preview renders author/date/anchor bubbles.
  // Backend: WordCommentContent in backend/office/models.py.
  comments?: OfficeWordComment[];
  // Round 15：每节页眉/页脚与目录域 instr 列表
  headers_footers?: WordHeaderFooterContent[];
  toc_fields?: string[];
  /**
   * Round C P4: bounded inline-image thumbnails (≤10 entries, backend
   * caps each data URL). `images - image_previews.length` = omitted count.
   * Backend: WordImagePreview in backend/office/models.py.
   */
  image_previews?: OfficeWordImagePreview[];
  // Round 57：脚注文本清单（无脚注为空表）
  footnotes?: string[];
  // Round 59：尾注文本清单（无尾注为空表）
  endnotes?: string[];
}

/** One Word comment (backend WordCommentContent). */
export interface OfficeWordComment {
  id: string;
  author?: string | null;
  date?: string | null;
  text: string;
  anchor_text?: string;
}

/** One inline-image thumbnail (backend WordImagePreview, round C P4). */
export interface OfficeWordImagePreview {
  index: number;
  content_type: string;
  data_url: string;
  thumbnail: boolean;
}

export interface OfficeExcelSheetContent {
  name: string;
  rows: string[][];
  max_row: number;
  max_col: number;
  /**
   * 公式视图 (item 1.4, additive): filled only when the read ran with
   * include_formulas=true — entries like 'B4=SUM(B2:B3)' (with a cached
   * value: 'B4=SUM(B2:B3) → 30'). null/absent = no formula view.
   * Backend field: backend/office/models.py:176-182.
   */
  formulas?: string[] | null;
  /** One-line hint shown when formulas lack cached values. */
  note?: string | null;
}

export interface OfficeExcelReadResult {
  summary: OfficeDocumentSummary;
  sheets: OfficeExcelSheetContent[];
}

// ──────────────────────────────────────────────────────────────────────
// PDF types (Office parity batch 1, item 1.2)
// Backend counterpart: PdfPageContent / PdfReadResult / PdfReadRequest /
// PdfPageSpec / PdfGenerateRequest / PdfGenerateResult in
// backend/office/models.py:419-481
// ──────────────────────────────────────────────────────────────────────

/** One extracted PDF page (backend `PdfPageContent`). */
export interface OfficePdfPageContent {
  page_number: number;
  text: string;
  tables: string[][][];
  images: Record<string, unknown>[];
}

/** Result of POST /api/v1/office/pdf/read (backend `PdfReadResult`). */
export interface OfficePdfReadResult {
  summary: OfficeDocumentSummary;
  pages: OfficePdfPageContent[];
  metadata: Record<string, unknown>;
}

/**
 * P1-C (office-p1c): result of POST /api/v1/office/import/convert-legacy
 * (backend `LegacyImportResult`).
 */
export interface OfficeLegacyImportResult {
  ok: boolean;
  converted_path?: string | null;
  converted_filename?: string | null;
  doc_type?: string | null;
  error?: string | null;
}

/**
 * P2-D (office-p2d): PDF AcroForm field + read/fill results
 * (backend `PdfFormField` / `PdfFormReadResult` / `PdfFormFillResult`).
 */
export interface OfficePdfFormField {
  name: string;
  type: string;
  value?: unknown;
  options?: string[] | null;
  required: boolean;
  read_only: boolean;
}

export interface OfficePdfFormReadResult {
  file_path: string;
  fields: OfficePdfFormField[];
  has_xfa: boolean;
}

export interface OfficePdfFormFillResult {
  output_path: string;
  filename: string;
  file_size_bytes: number;
  filled_count: number;
}

/**
 * P2-C (office-p2c): result of POST /api/v1/office/excel/recalc.
 */
export interface OfficeRecalcResult {
  ok: boolean;
  error?: string | null;
}

/**
 * F3 (office-p0): result of POST /api/v1/office/pdf/data — raw-PDF
 * base64 preview for the /office page's 原文预览 toggle (backend
 * `PdfDataResult`). Expected failures (oversize / path escape) come
 * back as `{ok:false,error}` rather than HTTP errors.
 */
export interface OfficePdfDataResult {
  ok: boolean;
  data_url?: string | null;
  error?: string | null;
}

/**
 * Request of POST /api/v1/office/pdf/read. Deliberately NOT
 * `OfficeReadRequest` — backend `PdfReadRequest` is `extra="forbid"`
 * and only accepts `workspace_path` + `file_path`.
 */
export interface OfficePdfReadRequest {
  workspace_path: string;
  file_path: string;
}

/** One page to generate in a PDF (backend `PdfPageSpec`). */
export interface PdfPageSpec {
  title?: string | null;
  paragraphs?: string[];
  tables?: string[][][];
}

/** Page size accepted by backend `generate_pdf` (backend/office/pdf.py:187-191). */
export type PdfPageSize = 'A4' | 'Letter' | 'Legal';

export interface OfficePdfGenerateRequest {
  /** P7: 进度追踪任务 id（前端 uuid；GET /office/progress/{id} 轮询） */
  task_id?: string;
  workspace_path: string;
  filename: string;
  pages: PdfPageSpec[];
  /** Backend default "A4"; unknown values fall back to A4 server-side. */
  page_size?: PdfPageSize;
  orientation?: 'portrait' | 'landscape';
}

/** Result of POST /api/v1/office/pdf/generate (backend `PdfGenerateResult`). */
export interface OfficePdfGenerateResult {
  output_path: string;
  filename: string;
  file_size_bytes: number;
  page_count: number;
}

export interface OfficeReadRequest {
  workspace_path: string;
  file_path: string;
  max_size_bytes?: number;
  /**
   * User-visible filename of the dropped/picked file. Optional on backend
   * (backend/office/models.py:189-209); included so the storage layer can
   * echo `original_filename` into the resulting OfficeDocumentSummary.
   */
  original_filename?: string;
}

// ──────────────────────────────────────────────────────────────────────
// Generate request types (Phase 1.4, plan §4.1.4)
// Backend counterpart: OfficePptGenerateRequest / OfficeWordGenerateRequest /
// OfficeExcelGenerateRequest in backend/office/models.py
// ──────────────────────────────────────────────────────────────────────

export interface PptSlideSpec {
  title: string;
  bullets?: string[];
  notes?: string;
  /** P5-B: 版式名（title/title_content/blank），后端按模板版式名匹配；缺省为 Blank */
  layout?: 'title_content' | 'title' | 'blank' | null;
}

export interface OfficePptGenerateRequest {
  /** P7: 进度追踪任务 id（前端 uuid；GET /office/progress/{id} 轮询） */
  task_id?: string;
  workspace_path: string;
  filename: string;
  slides: PptSlideSpec[];
  // Round 52：文档核心属性（与 Word/Excel 对称）
  metadata?: WordMetadataSpec;
}

export interface WordParagraphSpec {
  // Round 20：heading 扩展到 h4/h5
  heading?: 'h1' | 'h2' | 'h3' | 'h4' | 'h5';
  style?: 'bullet' | 'numbered';
  text: string;
  // Round 9：文中引用（references 条目 key；段落尾部上标 [N]，首现编号）
  citations?: string[];
}

// Word 版式规范（Round 7 FormatSpec —— "版式即配置"）。
// Backend counterpart: WordFormatSpec 系列模型 in backend/office/models.py。
// 全字段可选，不传时生成器保持既有默认版式。
export interface WordPageMarginsSpec {
  top?: number;
  bottom?: number;
  left?: number;
  right?: number;
}

export interface WordPageSetupSpec {
  size?: 'A4' | 'letter';
  orientation?: 'portrait' | 'landscape';
  margins_cm?: WordPageMarginsSpec;
  // Round 53：节内页码格式/起始号（论文前置罗马页码场景）
  page_number_format?:
    | 'decimal'
    | 'upperRoman'
    | 'lowerRoman'
    | 'upperLetter'
    | 'lowerLetter';
  page_number_start?: number;
  // Round 58：该节脚注编号每节重排（分章脚注场景）
  footnote_restart_each_section?: boolean;
}

/**
 * Round 26/37：分节横排（宽表/财务页场景）。
 * backend/office/models.py WordSectionBreakSpec 对应。
 */
export interface WordSectionBreakSpec {
  /** 该 0-based 段落下标起进入新节 */
  start_paragraph: number;
  page_setup: WordPageSetupSpec;
}

export interface WordBodyStyleSpec {
  font_size_pt?: number;
  line_spacing?: number;
  first_line_indent_cm?: number;
  space_after_pt?: number;
  align?: 'left' | 'center' | 'right' | 'justify';
}

export interface WordHeadingStyleSpec {
  font_size_pt?: number;
  bold?: boolean;
  color?: string;
  align?: 'left' | 'center' | 'right' | 'justify';
  space_before_pt?: number;
  space_after_pt?: number;
}

export interface WordHeaderFooterSpec {
  text?: string;
  align?: 'left' | 'center' | 'right' | 'justify';
  page_number?: boolean;
}

// 目录域设置（Round 13）：TOC 域由渲染器按标题样式生成（打开后更新域）。
// Backend counterpart: WordTocSpec in backend/office/models.py。
/**
 * Round 42：图目录/表目录设置（TOF 域 `TOC \c "图|表"`）。
 * backend/office/models.py WordIndexSpec 对应。
 */
export interface WordIndexSpec {
  heading_text?: string;
  placeholder_text?: string;
}

export interface WordTocSpec {
  heading_text?: string;
  levels?: string;
  placeholder_text?: string;
}

export interface WordFormatSpec {
  page?: WordPageSetupSpec;
  body?: WordBodyStyleSpec;
  // Round 20：headings 键扩展到 h4/h5
  headings?: Partial<Record<'h1' | 'h2' | 'h3' | 'h4' | 'h5', WordHeadingStyleSpec>>;
  title?: WordHeadingStyleSpec;
  header?: WordHeaderFooterSpec;
  footer?: WordHeaderFooterSpec;
  // Round 8：多级标题自动编号（h1-h5 → 1 / 1.1 / 1.1.1 … 文本前缀）
  numbering?: boolean;
  // Round 9：文末参考文献节样式（缺省：'参考文献' / 五号 / 悬挂缩进 0.74cm）
  bibliography?: BibliographySpec;
  // Round 13：目录域（None = 不插入目录）
  toc?: WordTocSpec;
  // Round 42：图目录/表目录（TOF 域，收录 SEQ 题注）
  figure_index?: WordIndexSpec;
  table_index?: WordIndexSpec;  // Round 33：首页不同页眉页脚（封面页场景）
  first_page_different?: boolean;
  first_page_header?: WordHeaderFooterSpec;
  first_page_footer?: WordHeaderFooterSpec;
  // Round 34：奇偶页不同页眉页脚（书籍排版场景）
  odd_even_pages?: boolean;
  // Round 26/37：分节横排（宽表/财务页场景）
  section_breaks?: WordSectionBreakSpec[];
  even_page_header?: WordHeaderFooterSpec;
  even_page_footer?: WordHeaderFooterSpec;
}

// Word 插图（Round 8）：支持行内放置与题注自动编号。
// Backend counterpart: WordImageSpec in backend/office/models.py。
export interface WordImageSpec {
  source: string;
  width_inches?: number;
  height_inches?: number;
  caption?: string;
  after_paragraph?: number;
}

// 结构化参考文献（Round 9 引用体系）。
// Backend counterpart: ReferenceSpec in backend/office/models.py。
export type ReferenceType =
  | 'journal'
  | 'book'
  | 'thesis'
  | 'conference'
  | 'report'
  | 'webpage'
  | 'patent'
  | 'standard'
  | 'newspaper';

export interface ReferenceSpec {
  key: string;
  ref_type?: ReferenceType;
  title: string;
  authors?: string[];
  year?: string;
  source?: string;
  volume?: string;
  issue?: string;
  pages?: string;
  publisher?: string;
  address?: string;
  url?: string;
  doi?: string;
  access_date?: string;
  language?: 'zh' | 'en';
}

export interface BibliographySpec {
  heading_text?: string;
  font_size_pt?: number;
  hanging_indent_cm?: number;
}

export interface WordCellMergeSpec {
  min_row: number;
  max_row: number;
  min_col: number;
  max_col: number;
}

export interface WordTableSpec {
  headers: string[];
  rows: string[][];
  caption?: string;
  style?: 'grid' | 'three_line';
  header_repeat?: boolean;
  column_widths_cm?: number[];
  merges?: WordCellMergeSpec[];
  // Round 36：表头行样式（加粗+浅灰底+居中）
  header_style?: boolean;
}

// Word 格式 Linter（Round 10）：对照 FormatSpec 校验 docx。
// Backend counterpart: WordLintIssue / WordLintResult / WordLintRequest
// in backend/office/models.py。
export interface WordLintIssue {
  rule_id: string;
  severity: 'error' | 'warning';
  message: string;
  fix_hint?: string;
}

export interface WordLintResult {
  ok: boolean;
  issue_count: number;
  error_count: number;
  warning_count: number;
  checked_rules: string[];
  issues: WordLintIssue[];
}

// Word 格式自动修复（Round 12）：lint → repair → 复检闭环。
// Backend counterpart: WordRepairResult / WordRepairRequest
// in backend/office/models.py。
export interface WordRepairResult {
  ok: boolean;
  repaired_rules: string[];
  output_path: string;
  overwrite: boolean;
  remaining: WordLintResult;
}

export interface WordRepairRequest {
  workspace_path: string;
  file_path: string;
  format_spec: WordFormatSpec;
  overwrite?: boolean;
  max_size_bytes?: number;
}

/**
 * A4b: Word lint (Round 10 linter) — backend counterpart:
 * backend/office/models.py WordLintIssue / WordLintResult / WordLintRequest.
 */
export interface OfficeWordLintIssue {
  rule_id: string;
  severity: 'error' | 'warning';
  message: string;
  fix_hint: string;
}

export interface OfficeWordLintResult {
  /** ok = no error-level issues. */
  ok: boolean;
  issue_count: number;
  error_count: number;
  warning_count: number;
  checked_rules: string[];
  issues: OfficeWordLintIssue[];
}

export interface OfficeWordLintRequest {
  workspace_path: string;
  file_path: string;
  format_spec: WordFormatSpec;
  max_size_bytes?: number;
}

/**
 * Round 49：文档核心属性（core properties，期刊/公文归档要求）。
 * backend/office/models.py WordMetadataSpec 对应。
 */
export interface WordMetadataSpec {
  author?: string;
  subject?: string;
  /** 关键词（分号分隔） */
  keywords?: string;
  comments?: string;
  category?: string;
}

export interface OfficeWordGenerateRequest {
  /** P7: 进度追踪任务 id（前端 uuid；GET /office/progress/{id} 轮询） */
  task_id?: string;
  workspace_path: string;
  filename: string;
  title: string;
  paragraphs?: WordParagraphSpec[];
  tables?: WordTableSpec[];
  images?: WordImageSpec[];
  font_family?: string;
  ascii_font?: string;
  format_spec?: WordFormatSpec;
  // Round 9 引用体系：结构化文献 + 引用样式
  references?: ReferenceSpec[];
  citation_style?: 'gbt7714' | 'apa';
  // Round 49：文档核心属性（core properties）
  metadata?: WordMetadataSpec;
}

export interface ExcelSheetSpec {
  name: string;
  headers?: string[];
  rows?: string[][];
  column_widths?: number[];
  // Round 14：表头样式 / 冻结首行 / 自适应列宽 / 按列名数字格式
  header_style?: boolean;
  freeze_header?: boolean;
  autofit_columns?: boolean;
  number_formats?: Record<string, string>;
  // Round 17：条件格式（数据条/色阶/重复值高亮）
  conditional_formats?: ExcelConditionalFormatSpec[];
  // Round 18：下拉数据验证（状态/分类列防手输错值）
  data_validations?: ExcelDataValidationSpec[];
  // Round 23：打印设置（方向/缩放/打印区域）
  print_setup?: ExcelPrintSetupSpec;
}

export interface ExcelPrintSetupSpec {
  orientation?: 'portrait' | 'landscape';
  fit_to_width?: number;
  print_area?: string;
  // Round 28：每页重复的标题行，如 '1:1'（长表打印每页带表头）
  title_rows?: string;
  // Round 31：打印页边距（厘米）
  margins_cm?: {
    top?: number;
    bottom?: number;
    left?: number;
    right?: number;
  };
  // Round 32：打印页眉/页脚文本（&P 为页码占位）
  print_header?: string;
  print_footer?: string;
}

export interface ExcelDataValidationSpec {
  range: string;
  options: string[];
  allow_blank?: boolean;
  prompt_title?: string;
  prompt?: string;
}

export interface ExcelConditionalFormatSpec {
  rule_type: 'data_bar' | 'color_scale' | 'duplicate' | 'icon_set';
  range: string;
  color?: string;
  min_color?: string;
  max_color?: string;
  fill_color?: string;
  // Round 19：icon_set 图标样式（默认 3Arrows）
  icon_style?:
    | '3Arrows'
    | '3TrafficLights1'
    | '3Signs'
    | '3Symbols'
    | '4Arrows'
    | '4RedToBlack'
    | '4Rating'
    | '5Arrows'
    | '5Rating';
}

export interface OfficeExcelGenerateRequest {
  /** P7: 进度追踪任务 id（前端 uuid；GET /office/progress/{id} 轮询） */
  task_id?: string;
  workspace_path: string;
  filename: string;
  sheets: ExcelSheetSpec[];
}

export interface OfficeDocumentListResponse {
  documents: OfficeDocumentSummary[];
  total: number;
}

export interface OfficeDeleteResponse {
  id: string;
  deleted: boolean;
}

// ──────────────────────────────────────────────────────────────────────
// Archive / restore + snapshot types (Office parity batch 1, item 1.7)
// ──────────────────────────────────────────────────────────────────────

/**
 * Response of POST /office/doc/{doc_id}/archive — mirrors the snapshot
 * restore shape: `{ ok, summary }` with the post-archive summary
 * (`archived_at` set).
 */
export interface OfficeArchiveResponse {
  ok: boolean;
  summary: OfficeDocumentSummary;
}

/** Response of POST /office/doc/{doc_id}/restore (`archived_at` cleared). */
export interface OfficeRestoreResponse {
  ok: boolean;
  summary: OfficeDocumentSummary;
}

/** One pre-edit snapshot (backend `<ms>-<generated_filename>` file). */
export interface OfficeSnapshotMeta {
  /** Snapshot filename `<ms>-<generated_filename>`. */
  snapshot_id: string;
  size_bytes: number;
  /** Unix epoch in milliseconds. */
  created_at: number;
}

/** Response of GET /office/doc/{doc_id}/snapshots. */
export interface OfficeSnapshotListResponse {
  snapshots: OfficeSnapshotMeta[];
}

/** Response of POST /office/doc/{doc_id}/snapshots/{snapshot_id}/restore. */
export interface OfficeSnapshotRestoreResponse {
  ok: boolean;
  summary: OfficeDocumentSummary;
}

// ──────────────────────────────────────────────────────────────────────
// Update preview + PDF export (Office parity batch 2 — items 2.5 / 2.7)
// Backend counterpart: backend/office/diff_preview.py (DiffPreviewChange /
// DiffPreviewResult / OfficeUpdatePreviewRequest) and
// backend/office/export_pdf.py (ExportPdfResult; OfficeExportPdfRequest
// lives in the same module).
// NOTE (round 2, R1): batch 2 shipped preview-only — there was no
// page-level apply-update route and real updates went through the
// chat-driven office_update tool. Round 2 adds POST
// /office/doc/{doc_id}/update (types below), so the edit-preview dialog
// now applies in-page after a successful preview.
// ──────────────────────────────────────────────────────────────────────

/**
 * One update op, passed through verbatim to the backend editor. Ops are
 * plain dicts on the backend too (runtime-validated there) — see the op
 * reference in backend/office/edit.py (e.g. word replace_text
 * `{find, replace}`, excel set_cells `{sheet, cells:[{addr, value}]}`,
 * ppt set_slide_title `{index, title}`).
 */
