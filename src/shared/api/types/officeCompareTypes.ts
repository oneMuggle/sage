/**
 * Cross-document compare wire types (M6b).
 *
 * Backend counterpart:
 *   POST /api/v1/office/compare  → backend/office/compare.py
 *
 * Bodies and responses stay snake_case (Electron relay forwards verbatim).
 * The unified-extraction contract (`POST /office/extract`) gets its TS
 * types together with its first frontend consumer.
 */

/** Request of POST /api/v1/office/compare (backend CompareRequest). */
export interface OfficeCompareRequest {
  workspace_path: string;
  left_path: string;
  right_path: string;
  /** Backend default 2000, clamped to 20..10000. */
  max_report_lines?: number;
}

/** One added/removed line from the unified diff. */
export interface OfficeCompareChange {
  kind: 'added' | 'removed';
  text: string;
}

/** Line-level diff counts (backend CompareSummary). */
export interface OfficeCompareSummary {
  added: number;
  removed: number;
  unchanged: number;
}

/** Result of POST /api/v1/office/compare (backend CompareResult). */
export interface OfficeCompareResult {
  ok: boolean;
  format: string;
  left_path: string;
  right_path: string;
  summary: OfficeCompareSummary;
  changes: OfficeCompareChange[];
  /** Ready-to-display Markdown diff report. */
  report_markdown: string;
  warnings: Record<string, string>[];
}
