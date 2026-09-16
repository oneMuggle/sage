/**
 * Sage API - Office document API (Phase 1.3, plan §4.1.3 step 12)
 *
 * Backend counterpart: backend/api/office_routes.py (mounted at /api/v1/office).
 * Frontend never calls HTTP directly — it uses IPC bridge via invoke().
 *
 * M0 Task 6 (2026-07-23): removed withRetry from side-effecting calls
 * (read, generate, delete). Idempotent listDocuments keeps the bounded
 * retry (the existing error classifier marks transient network failures
 * there). Side-effecting calls can corrupt user files if auto-retried —
 * e.g. a parse that fails on a first read would just discard the import
 * and the user re-imports; without retry the user sees the error
 * immediately and decides what to do.
 */

import { invoke } from './desktopInvoke';
import type {
  OfficeArchiveResponse,
  OfficeCapabilities,
  OfficeDeleteResponse,
  OfficeDocUpdateRequest,
  OfficeDocUpdateResponse,
  OfficeDocumentListResponse,
  OfficeExcelGenerateRequest,
  OfficeExcelReadResult,
  OfficeExportPdfRequest,
  OfficeExportPdfResult,
  OfficePdfGenerateRequest,
  OfficePdfGenerateResult,
  OfficePdfPreviewResult,
  OfficePdfReadRequest,
  OfficeLegacyImportResult,
  OfficePdfDataResult,
  OfficePdfReadResult,
  OfficePptGenerateRequest,
  OfficePptReadResult,
  OfficeReadRequest,
  OfficeRestoreResponse,
  OfficeSnapshotListResponse,
  OfficeSnapshotRestoreResponse,
  OfficeTemplateInstantiateRequest,
  OfficeTemplateInstantiateResult,
  OfficeTemplateListResponse,
  OfficeTemplateThumbnailResult,
  OfficeUpdatePreviewRequest,
  OfficeUpdatePreviewResult,
  OfficeWordGenerateRequest,
  OfficeWordLintRequest,
  OfficeWordLintResult,
  OfficeWordReadResult,
} from './types';
import { handleApiError, withRetry } from './utils';

export const officeApi = {
  /**
   * Read a .pptx file → OfficePptReadResult (slides + summary).
   *
   * No retry — a parse failure should surface immediately so the caller
   * can discard the staged import via `discardOfficeImport`.
   */
  async readPpt(req: OfficeReadRequest): Promise<OfficePptReadResult> {
    try {
      return await invoke<OfficePptReadResult>('office_ppt_read', {
        workspacePath: req.workspace_path,
        filePath: req.file_path,
        maxSizeBytes: req.max_size_bytes,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * Read a .docx file → OfficeWordReadResult (paragraphs + tables + summary).
   *
   * No retry — see readPpt.
   */
  async readWord(req: OfficeReadRequest): Promise<OfficeWordReadResult> {
    try {
      return await invoke<OfficeWordReadResult>('office_word_read', {
        workspacePath: req.workspace_path,
        filePath: req.file_path,
        maxSizeBytes: req.max_size_bytes,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * Read a .xlsx file → OfficeExcelReadResult (sheets + summary).
   *
   * No retry — see readPpt.
   */
  async readExcel(req: OfficeReadRequest): Promise<OfficeExcelReadResult> {
    try {
      return await invoke<OfficeExcelReadResult>('office_excel_read', {
        workspacePath: req.workspace_path,
        filePath: req.file_path,
        maxSizeBytes: req.max_size_bytes,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * Read a .pdf file → OfficePdfReadResult (pages + summary + metadata).
   *
   * No retry — see readPpt. NOTE: the backend PdfReadRequest model is
   * `extra="forbid"`, so only workspace_path + file_path are sent (no
   * max_size_bytes / original_filename, unlike the OOXML read requests).
   */
  async readPdf(req: OfficePdfReadRequest): Promise<OfficePdfReadResult> {
    try {
      return await invoke<OfficePdfReadResult>('office_pdf_read', {
        workspacePath: req.workspace_path,
        filePath: req.file_path,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * F3 (office-p0): raw-PDF base64 preview for the /office page's
   * 原文预览 toggle — returns a `data:application/pdf` URL the renderer
   * embeds in an iframe (Chromium built-in viewer). Backend validates
   * the managed path and enforces the same 20MB cap as the chat
   * artifact viewer; expected failures come back as `{ok:false,error}`
   * instead of a thrown transport error.
   */
  /**
   * P1-C (office-p1c): convert a staged legacy (.doc/.xls/.ppt) copy
   * inside the managed workspace into the modern format in place.
   * Expected failures (soffice missing / conversion error) come back as
   * `{ok:false,error}` — callers drive the import-discard flow from it.
   */
  async convertLegacyImport(req: OfficePdfReadRequest): Promise<OfficeLegacyImportResult> {
    try {
      return await invoke<OfficeLegacyImportResult>('office_import_convert_legacy', {
        workspacePath: req.workspace_path,
        filePath: req.file_path,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  async readPdfData(req: OfficePdfReadRequest): Promise<OfficePdfDataResult> {
    try {
      return await invoke<OfficePdfDataResult>('office_pdf_data', {
        workspacePath: req.workspace_path,
        filePath: req.file_path,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * List all office documents in a workspace.
   *
   * Bounded retry is retained here — list is read-only and idempotent,
   * so transient network failures can be safely retried without risk
   * to the user's data.
   *
   * `includeArchived` (item 1.7): also return soft-deleted rows
   * (`archived_at` set) so the archive-restore UI can list them. The
   * backend default keeps them hidden.
   */
  async listDocuments(
    workspacePath: string,
    opts?: { includeArchived?: boolean },
  ): Promise<OfficeDocumentListResponse> {
    return withRetry(async () => {
      try {
        return await invoke<OfficeDocumentListResponse>('office_list_documents', {
          workspacePath,
          includeArchived: opts?.includeArchived ?? false,
        });
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },

  /**
   * Delete an office document record by id (does not delete the file itself).
   *
   * No retry — kept unreachable from the management view; archive/restore
   * (item 1.7) is the user-facing soft-delete path. Exposed here only for
   * legacy callers that explicitly opt in.
   */
  async deleteDocument(docId: string): Promise<OfficeDeleteResponse> {
    try {
      return await invoke<OfficeDeleteResponse>('office_delete_document', { docId });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * Archive (soft-delete) a document by id (item 1.7).
   *
   * Sets `archived_at` so the row hides from the default list view but
   * stays recoverable via `restoreDocument`. Idempotent server-side:
   * re-archiving returns the existing timestamp.
   *
   * No retry — side-effecting (same policy as deleteDocument).
   */
  async archiveDocument(docId: string): Promise<OfficeArchiveResponse> {
    try {
      return await invoke<OfficeArchiveResponse>('office_archive_document', { docId });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * Restore (un-archive) a document by id (item 1.7).
   *
   * Clears `archived_at` so the row reappears in the default list view.
   * Idempotent server-side. No retry — side-effecting.
   */
  async restoreDocument(docId: string): Promise<OfficeRestoreResponse> {
    try {
      return await invoke<OfficeRestoreResponse>('office_restore_document', { docId });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * List pre-edit snapshots for a document (item 1.7).
   *
   * Snapshots live in `<managed_dir>/.snapshots/<ms>-<filename>`; each
   * entry carries `snapshot_id` (the filename), `size_bytes` and
   * `created_at` (ms epoch).
   *
   * Bounded retry — read-only and idempotent, same policy as listDocuments.
   */
  async listSnapshots(docId: string): Promise<OfficeSnapshotListResponse> {
    return withRetry(async () => {
      try {
        return await invoke<OfficeSnapshotListResponse>('office_list_snapshots', { docId });
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },

  /**
   * Round B P2: structured diff between a pre-edit snapshot and the
   * current document (snapshot=before, current=after) — same
   * DiffPreviewResult shape the edit-preview dialog renders. Parse
   * failures fold to `{ok:false, error}`; unknown doc still throws 404.
   *
   * Bounded retry — read-only and idempotent.
   */
  async diffSnapshot(docId: string, snapshotId: string): Promise<OfficeUpdatePreviewResult> {
    return withRetry(async () => {
      try {
        return await invoke<OfficeUpdatePreviewResult>('office_snapshot_diff', {
          docId,
          snapshotId,
        });
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },

  /**
   * Restore a document's managed file from a snapshot (item 1.7).
   *
   * Overwrites the current managed file with the snapshot's bytes. No
   * retry — side-effecting (a transient blip must not double-restore).
   */
  async restoreSnapshot(docId: string, snapshotId: string): Promise<OfficeSnapshotRestoreResponse> {
    try {
      return await invoke<OfficeSnapshotRestoreResponse>('office_restore_snapshot', {
        docId,
        snapshotId,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * Generate a .pptx file (Phase 1.4). Returns { output_path, filename, file_size_bytes }.
   *
   * No retry — generation is side-effecting. We don't want a transient
   * network blip to silently produce a duplicate file.
   */
  async generatePpt(
    req: OfficePptGenerateRequest,
  ): Promise<{ output_path: string; filename: string; file_size_bytes: number }> {
    try {
      return await invoke('office_ppt_generate', {
        workspacePath: req.workspace_path,
        filename: req.filename,
        slides: req.slides,
        task_id: req.task_id,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * Generate a .docx file (Phase 1.4). Returns { output_path, filename, file_size_bytes }.
   *
   * No retry — see generatePpt.
   */
  async generateWord(
    req: OfficeWordGenerateRequest,
  ): Promise<{ output_path: string; filename: string; file_size_bytes: number }> {
    try {
      return await invoke('office_word_generate', {
        workspacePath: req.workspace_path,
        filename: req.filename,
        title: req.title,
        paragraphs: req.paragraphs,
        tables: req.tables,
        task_id: req.task_id,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * Generate a .xlsx file (Phase 1.4). Returns { output_path, filename, file_size_bytes }.
   *
   * No retry — see generatePpt.
   */
  async generateExcel(
    req: OfficeExcelGenerateRequest,
  ): Promise<{ output_path: string; filename: string; file_size_bytes: number }> {
    try {
      return await invoke('office_excel_generate', {
        workspacePath: req.workspace_path,
        filename: req.filename,
        sheets: req.sheets,
        task_id: req.task_id,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * A4b: lint a .docx against a WordFormatSpec (Round 10 linter).
   *
   * Read-only — no retry needed, but unlike generate* a retry would be
   * harmless; kept retry-free for consistency with the read* methods.
   * NOTE: backend WordLintRequest is extra="forbid" — only the four
   * documented args are sent (maxSizeBytes omitted when undefined).
   */
  async lintWord(req: OfficeWordLintRequest): Promise<OfficeWordLintResult> {
    try {
      return await invoke<OfficeWordLintResult>('office_word_lint', {
        workspacePath: req.workspace_path,
        filePath: req.file_path,
        formatSpec: req.format_spec,
        ...(req.max_size_bytes !== undefined ? { maxSizeBytes: req.max_size_bytes } : {}),
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * Generate a .pdf file (Office parity batch 1, item 1.2).
   * Returns { output_path, filename, file_size_bytes, page_count }.
   *
   * No retry — see generatePpt.
   */
  async generatePdf(req: OfficePdfGenerateRequest): Promise<OfficePdfGenerateResult> {
    try {
      return await invoke<OfficePdfGenerateResult>('office_pdf_generate', {
        workspacePath: req.workspace_path,
        filename: req.filename,
        pages: req.pages,
        pageSize: req.page_size,
        orientation: req.orientation,
        task_id: req.task_id,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * Dry-run update ops against a temp COPY of the document (batch 2,
   * item 2.5) — the source file is never touched. Resolves the target
   * by doc_id when given (managed-layout lookup server-side), else by
   * file_path. Invalid ops come back as
   * `{ok: false, changes: [], error}` so the UI can show WHY the real
   * update would fail.
   *
   * Round 2 (R1): the apply counterpart is `updateDocument` — the
   * dialog previews first, then applies the SAME ops on user confirm.
   *
   * No retry — runs the full editor pipeline per op.
   */
  async previewUpdate(req: OfficeUpdatePreviewRequest): Promise<OfficeUpdatePreviewResult> {
    try {
      return await invoke<OfficeUpdatePreviewResult>('office_update_preview', {
        workspacePath: req.workspace_path,
        filePath: req.file_path,
        docId: req.doc_id,
        ops: req.ops,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * Apply previously previewed update ops to the document (round 2, R1).
   *
   * POST /api/v1/office/doc/{doc_id}/update body {ops} — the same op
   * dicts `previewUpdate` dry-ran. Resolves the target by doc_id
   * (managed-layout lookup server-side). Returns
   * `{ok, summary, self_check}` where `summary` is the post-update
   * document row (status='edited') and `self_check` reports whether a
   * post-apply re-read confirmed the ops landed.
   *
   * Errors (unknown doc → 404, invalid ops → 422, both
   * `{error_type, message, file_path}`) throw via handleApiError —
   * there is no ok=false transport shape.
   *
   * No retry — side-effecting (writes the managed file; a transient
   * blip must not double-apply).
   */
  async updateDocument(req: OfficeDocUpdateRequest): Promise<OfficeDocUpdateResponse> {
    try {
      return await invoke<OfficeDocUpdateResponse>('office_doc_update', {
        docId: req.doc_id,
        ops: req.ops,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * Export a workspace .docx/.xlsx/.pptx to PDF via locally installed
   * converters (batch 2, item 2.7) — LibreOffice headless first, then
   * MS Word COM (Windows/.docx). Output lands next to the source as
   * `<stem>.pdf`.
   *
   * Never throws for converter problems: failures come back as
   * `{ok: false, method: null, output_path: null, error}`. HTTP-level
   * failures (4xx/5xx, backend down) still throw via handleApiError.
   *
   * No retry — conversion is side-effecting (overwrites the output PDF).
   */
  async exportPdf(req: OfficeExportPdfRequest): Promise<OfficeExportPdfResult> {
    try {
      return await invoke<OfficeExportPdfResult>('office_export_pdf', {
        workspacePath: req.workspace_path,
        filePath: req.file_path,
        task_id: req.task_id,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * Probe local Office environment capabilities (round A, P6) —
   * LibreOffice / Word COM / Pillow / formulas availability for the
   * capability badges + install guidance on the Office page.
   *
   * Bounded retry — read-only and idempotent (the backend caches the
   * probe for 30s anyway). Pass force=true to bypass that cache when
   * the user clicks 重新检测.
   */
  async getCapabilities(force = false): Promise<OfficeCapabilities> {
    try {
      return await withRetry(() =>
        invoke<OfficeCapabilities>('office_capabilities', force ? { force: true } : {}),
      );
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * High-fidelity PDF preview (round A, P1) — converts a managed
   * docx/xlsx/pptx to PDF in the workspace preview cache and returns a
   * data URL for the embedded Chromium viewer. Converter problems come
   * back as `{ok: false, error}` (HTTP failures still throw).
   *
   * No retry — conversion spawns a subprocess; the user can re-toggle.
   */
  async pdfPreview(req: OfficeExportPdfRequest): Promise<OfficePdfPreviewResult> {
    try {
      return await invoke<OfficePdfPreviewResult>('office_pdf_preview', {
        workspacePath: req.workspace_path,
        filePath: req.file_path,
        task_id: req.task_id,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * Round C P5: template first-page thumbnail (PNG data URL). Server-side
   * disk cache makes repeats cheap; failures fold to `{ok:false}` and the
   * caller degrades silently (thumbnails are decorative).
   *
   * No retry — first render spawns a converter subprocess.
   */
  async templateThumbnail(req: {
    workspace_path: string;
    template_id?: string;
    workspace_template?: string;
  }): Promise<OfficeTemplateThumbnailResult> {
    try {
      return await invoke<OfficeTemplateThumbnailResult>('office_template_thumbnail', {
        workspacePath: req.workspace_path,
        templateId: req.template_id,
        workspaceTemplate: req.workspace_template,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * List document templates available in a workspace (batch 3, item 3.2;
   * round 3 N2 adds excel/ppt) — builtin entries shipped with the backend
   * plus the workspace's own `templates/*.docx|xlsx|pptx`. Each entry
   * carries `doc_type`; the picker filters on the tab's kind so unknown
   * future kinds degrade gracefully.
   *
   * Bounded retry — read-only and idempotent, same policy as listDocuments.
   */
  async listTemplates(workspacePath: string): Promise<OfficeTemplateListResponse> {
    return withRetry(async () => {
      try {
        return await invoke<OfficeTemplateListResponse>('office_list_templates', {
          workspacePath,
        });
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },

  /**
   * Instantiate a template with placeholder data (batch 3, item 3.2;
   * round 3 N2: works for word/excel/ppt templates — the backend picks
   * the filler by the template's doc_type). Returns
   * `output_path` / `filename` / `file_size_bytes` / `filled_count` /
   * `unfilled_placeholders`. The backend persists a document row, so the
   * result shows up in the document list after a refresh.
   *
   * Route is `rawBody` — see OfficeTemplateInstantiateRequest for why the
   * placeholder-name keys in `data` / `images` must not be key-translated.
   *
   * No retry — side-effecting (creates a new OOXML file + document row).
   */
  async instantiateTemplate(
    req: OfficeTemplateInstantiateRequest,
  ): Promise<OfficeTemplateInstantiateResult> {
    try {
      return await invoke<OfficeTemplateInstantiateResult>('office_templates_instantiate', {
        workspacePath: req.workspace_path,
        templateId: req.template_id,
        workspaceTemplate: req.workspace_template,
        filename: req.filename,
        data: req.data,
        images: req.images,
        task_id: req.task_id,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * P7: 轮询 office 长任务进度（生成/导出期间的阶段 + 百分比）。
   *
   * 任务不存在（未开始/已结束）时后端返回 `active: false` 而非 404，
   * 轮询方据此判定完成，无需异常处理。
   */
  async getOfficeProgress(
    taskId: string,
  ): Promise<{ active: boolean; stage: string | null; percent: number | null }> {
    try {
      return await invoke('office_get_progress', { taskId });
    } catch (error) {
      throw handleApiError(error);
    }
  },
};
