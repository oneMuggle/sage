/**
 * PDF wire types (Office parity batch 1, item 1.2).
 *
 * Backend counterpart: PdfPageContent / PdfReadResult / PdfReadRequest /
 * PdfPageSpec / PdfGenerateRequest / PdfGenerateResult in
 * backend/office/models.py:419-481
 *
 * Split out of `src/shared/api/types.ts` to keep the barrel under the
 * 800-line architecture cap; re-exported from `types.ts` so every existing
 * `from '../../shared/api/types'` import keeps working unchanged.
 */

import type { OfficeDocumentSummary } from '../types';

/** One extracted PDF page (backend `PdfPageContent`). */
export interface OfficePdfPageContent {
  page_number: number;
  text: string;
  tables: string[][][];
  images: Record<string, unknown>[];
  /**
   * M6c: number of embedded images detected on this page.
   * `images` may hold fewer entries than this (per-page cap / precheck
   * rejection / document budget), so `images_omitted` explains the gap.
   */
  image_count?: number;
  /**
   * M6c: images detected on this page but NOT returned (dropped by the
   * per-page cap, the decode precheck, or the document-wide budget).
   */
  images_omitted?: number;
  /** P4-A (office-p4a): page text came from the OCR fallback (scanned page). */
  ocr?: boolean;
}

/** Result of POST /api/v1/office/pdf/read (backend `PdfReadResult`). */
export interface OfficePdfReadResult {
  summary: OfficeDocumentSummary;
  pages: OfficePdfPageContent[];
  metadata: Record<string, unknown>;
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
 * `OfficeReadRequest` — backend `PdfReadRequest` is `extra="forbid"`:
 * only the fields declared here are accepted.
 *
 * M6c: image extraction is fully opt-in — `include_images=false` skips
 * enumeration entirely; pixels additionally require `embed_image_data`.
 */
export interface OfficePdfReadRequest {
  workspace_path: string;
  file_path: string;
  /** M6c: enumerate embedded images (metadata only by default). */
  include_images?: boolean;
  /** M6c: per-page image cap, backend clamps to 0..10 (default 3). */
  max_images_per_page?: number;
  /** M6c: embed base64 pixels (default false; server budgets apply). */
  embed_image_data?: boolean;
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
