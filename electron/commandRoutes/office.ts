/**
 * Office IPC commands — renderer: src/shared/api/officeApi.ts; backend: backend/api/office_routes.py
 * (router prefix /office, mounted under /api/v1).
 *
 * Restored by the IPC-bridge repair. #857 ("三阶段 AI 工作区优化") merged over commands.ts and
 * silently dropped these 10 entries while officeApi.ts kept calling them, so every call threw
 * UnknownIpcCommandError at runtime (PDF/Word preview, Excel recalc, PDF forms, snapshot diff,
 * capability bar).
 *
 * They were NOT pasted back verbatim: each one was re-checked against the current backend route
 * and request model (all of them are `extra="forbid"`). That turned up one latent bug in the old
 * mapping — see office_pdf_fill_form.
 */
import type { CommandRoute } from '../commands';

export const officeRoutes: Record<string, CommandRoute> = {
  // Round A (P6): capability probe (converters / optional deps); `force` bypasses the 30 s server cache.
  office_capabilities: {
    method: 'GET',
    path: (a) => `/api/v1/office/capabilities${a.force ? '?force=true' : ''}`,
  },

  // Round A (P1): high-fidelity preview — docx/xlsx/pptx -> cached PDF -> data URL.
  // Body is OfficeExportPdfRequest: workspace_path + file_path (+ task_id).
  office_pdf_preview: { method: 'POST', path: () => '/api/v1/office/pdf-preview' },

  // F3 / P2-B: managed PDF / docx as a base64 data URL (the /office page's "原文预览" toggle,
  // docx-preview native render). PdfDataRequest is extra=forbid: send ONLY workspacePath + filePath.
  office_pdf_data: { method: 'POST', path: () => '/api/v1/office/pdf/data' },
  office_word_data: { method: 'POST', path: () => '/api/v1/office/word/data' },

  // P2-C: recalc the formula cache of a managed .xlsx in place (soffice; snapshot taken first).
  office_excel_recalc: { method: 'POST', path: () => '/api/v1/office/excel/recalc' },

  // P1-C: legacy .doc/.xls/.ppt staging copy -> modern format. LegacyImportRequest is extra=forbid:
  // send ONLY workspacePath + filePath.
  office_import_convert_legacy: {
    method: 'POST',
    path: () => '/api/v1/office/import/convert-legacy',
  },

  // P2-D: PDF AcroForm read / fill (OfficePreviewPanel form dialog).
  office_pdf_read_form: { method: 'POST', path: () => '/api/v1/office/pdf/read-form' },

  // `data` maps PDF form-field NAMES to values. Those names are user data, not JS identifiers, and
  // the backend matches them verbatim (`if widget.field_name in req.data`) and silently ignores
  // the rest. The bridge's camelCase->snake_case pass recurses into nested objects, so left to
  // itself it would rewrite a field `firstName` to `first_name` and `Name` to `_name`: the form
  // saves "successfully" with those fields empty. rawBody skips that pass; the top-level keys are
  // spelled out in snake_case here (PdfFormFillRequest is extra=forbid).
  office_pdf_fill_form: {
    method: 'POST',
    path: () => '/api/v1/office/pdf/fill-form',
    rawBody: true,
    body: (a) => ({
      workspace_path: a.workspacePath ?? a.workspace_path,
      template_path: a.templatePath ?? a.template_path,
      output_filename: a.outputFilename ?? a.output_filename,
      data: a.data,
      flatten: a.flatten,
    }),
  },

  // Round B (P2): snapshot vs current structured diff (snapshot = before). Read-only.
  office_snapshot_diff: {
    method: 'GET',
    path: (a) =>
      `/api/v1/office/doc/${encodeURIComponent(String(a.docId ?? a.doc_id))}/snapshots/${encodeURIComponent(String(a.snapshotId ?? a.snapshot_id))}/diff`,
  },

  // Round C (P5): template first-page thumbnail (PNG data URL, disk-cached server-side). POST
  // because generation writes the cache and the request carries a body.
  office_template_thumbnail: {
    method: 'POST',
    path: () => '/api/v1/office/templates/thumbnail',
  },

  // Office document features (Phase 1.3, plan §4.1.3 step 14).
  // 5 routes for Phase 1.2 backend (3 read + list + delete).
  // Generate endpoints (ppt_generate, word_generate, excel_generate)
  // deferred to Phase 1.4 follow-up PR.
  office_ppt_read: { method: 'POST', path: () => '/api/v1/office/ppt/read' },
  office_word_read: { method: 'POST', path: () => '/api/v1/office/word/read' },
  office_excel_read: { method: 'POST', path: () => '/api/v1/office/excel/read' },
  // A4b: Word 交付包格式校验 —— POST /office/word/lint。
  // NOTE: WordLintRequest is extra="forbid" — officeApi.lintWord must send
  // ONLY workspacePath + filePath + formatSpec (+ optional maxSizeBytes).
  office_word_lint: { method: 'POST', path: () => '/api/v1/office/word/lint' },
  // P0-2 (2026-10-01): Word 格式自动修复 —— POST /office/word/repair。
  // 后端 repair_docx 默认写 <stem>-repaired.docx，overwrite=true 时原子替换原
  // 文件，并自动复检把 remaining 带回。接线前该端点全仓零调用，"一键修复"
  // 在 UI 上不存在（只报问题不给修法）。
  office_word_repair: { method: 'POST', path: () => '/api/v1/office/word/repair' },
  // Office parity batch 1 (item 1.2): PDF read/generate.
  // Backend: backend/api/office_routes.py:495-508 (POST /pdf/read, POST /pdf/generate).
  // NOTE: PdfReadRequest is extra="forbid" — officeApi.readPdf must send
  // ONLY workspacePath + filePath (no max_size_bytes / original_filename).
  office_pdf_read: { method: 'POST', path: () => '/api/v1/office/pdf/read' },
  // include_archived (item 1.7): archive-restore UI lists soft-deleted rows.
  // Path builder reads the raw camelCase arg and serializes snake_case into
  // the query string (query args are NOT auto-translated by invokeBackend).
  office_list_documents: {
    method: 'GET',
    path: (a) => {
      let path = `/api/v1/office/documents?workspace_path=${encodeURIComponent(String(a.workspacePath))}`;
      if (a.includeArchived === true) path += '&include_archived=true';
      return path;
    },
  },
  office_delete_document: {
    method: 'DELETE',
    path: (a) => `/api/v1/office/documents/${encodeURIComponent(String(a.docId))}`,
  },
  // Phase 1.4 (2026-07-16): Office generate endpoints (plan §4.1.4 step 19).
  office_ppt_generate: { method: 'POST', path: () => '/api/v1/office/ppt/generate' },
  office_word_generate: { method: 'POST', path: () => '/api/v1/office/word/generate' },
  office_excel_generate: { method: 'POST', path: () => '/api/v1/office/excel/generate' },
  office_pdf_generate: { method: 'POST', path: () => '/api/v1/office/pdf/generate' },
  // P7 (2026-09-14): office 长任务进度轮询（任务不存在时后端返回 active:false）。
  office_get_progress: {
    method: 'GET',
    path: (a) => `/api/v1/office/progress/${encodeURIComponent(String(a.taskId))}`,
  },
  // Office parity batch 1 (item 1.7): archive/restore + snapshot lifecycle.
  // Backend service layer lives in backend/office/tool_service.py:601-716
  // (archive / restore) and backend/office/storage.py:316-360 (snapshots);
  // the HTTP routes land in backend/api/office_routes.py in the same batch.
  // Route prefix follows the agreed snapshot contract (/office/doc/{id}/…).
  office_archive_document: {
    method: 'POST',
    path: (a) => `/api/v1/office/doc/${encodeURIComponent(String(a.docId))}/archive`,
  },
  office_restore_document: {
    method: 'POST',
    path: (a) => `/api/v1/office/doc/${encodeURIComponent(String(a.docId))}/restore`,
  },
  office_list_snapshots: {
    method: 'GET',
    path: (a) => `/api/v1/office/doc/${encodeURIComponent(String(a.docId))}/snapshots`,
  },
  office_restore_snapshot: {
    method: 'POST',
    path: (a) =>
      `/api/v1/office/doc/${encodeURIComponent(String(a.docId))}/snapshots/${encodeURIComponent(String(a.snapshotId))}/restore`,
  },
  // Office parity batch 2 (items 2.5 / 2.7): update PREVIEW (dry-run —
  // applies ops to a temp copy, never the source) and explicit PDF export.
  // Backend: backend/api/office_routes.py:620-658 (POST /update/preview,
  // POST /export-pdf). Batch 2 shipped preview-only — real edits stayed on
  // the chat-driven office_update tool path; round 2 (R1) adds the
  // page-level office_doc_update route right below.
  // Body keys (workspacePath/filePath/docId/ops) pass through the normal
  // recursive camelToSnakeKeys; the composed op dicts use only lowercase
  // single-word keys (find/replace/sheet/cells/addr/value/index/title),
  // so the translation is a no-op on them.
  office_update_preview: { method: 'POST', path: () => '/api/v1/office/update/preview' },
  office_export_pdf: { method: 'POST', path: () => '/api/v1/office/export-pdf' },

  // Office parity round 2 (R1): page-level apply-update — closes the
  // edit-preview loop opened by office_update_preview. Backend contract:
  // POST /api/v1/office/doc/{doc_id}/update body {ops} (same op dicts the
  // preview route takes) → {ok, summary, self_check:{ok, summary?, error?}}.
  // Unknown doc → 404 {error_type, message, file_path}; invalid ops → 422
  // same shape. rawBody: op dicts are forwarded to the backend editor
  // verbatim (runtime-validated there). The recursive camelToSnakeKeys is
  // a no-op on the lowercase single-word keys this dialog composes today
  // (find/replace/sheet/cells/addr/value/index/title), but ops are
  // pass-through user-shaped data — any future camelCase op key (e.g.
  // "cellRange") would be mangled into "_cell_range", so the body is
  // built explicitly snake_case instead (doc_id rides in the path and
  // must not leak into the body).
  office_doc_update: {
    method: 'POST',
    path: (a) => `/api/v1/office/doc/${encodeURIComponent(String(a.docId))}/update`,
    rawBody: true,
    // F1 (P0-A): the optimistic-concurrency fields ride in the same body.
    // Both are optional — omitted keys keep the pre-guard behaviour.
    body: (a) => ({
      ops: Array.isArray(a.ops) ? (a.ops as Record<string, unknown>[]) : [],
      ...(typeof a.expectedRevision === 'string' && a.expectedRevision
        ? { expected_revision: a.expectedRevision }
        : {}),
      ...(typeof a.idempotencyKey === 'string' && a.idempotencyKey
        ? { idempotency_key: a.idempotencyKey }
        : {}),
    }),
  },

  // F1/F2 (P0-A): content revision probe for the preview caches. GET
  // /api/v1/office/doc/{doc_id}/revision → {doc_id, revision, size_bytes,
  // mtime_ms}. Read-only; unknown doc → 404 like the other doc routes.
  office_doc_revision: {
    method: 'GET',
    path: (a) => `/api/v1/office/doc/${encodeURIComponent(String(a.docId))}/revision`,
  },

  // Office parity batch 3 (item 3.2): Word template library (从模板创建).
  // Backend: backend/api/office_routes.py — GET /templates (builtin +
  // workspace *.docx) and POST /templates/instantiate (→ WordTemplateFillResult).
  office_list_templates: {
    method: 'GET',
    path: (a) =>
      `/api/v1/office/templates?workspace_path=${encodeURIComponent(String(a.workspacePath))}`,
  },
  // rawBody: the `data` / `images` maps are keyed by template placeholder
  // names — user data, not JS identifiers. The default camelToSnakeKeys
  // would mangle e.g. "ReportDate" into "_report_date", so the route skips
  // translation and the body builder maps the top-level fields to the
  // backend's snake_case contract explicitly; placeholder keys inside the
  // maps pass through untouched.
  office_templates_instantiate: {
    method: 'POST',
    path: () => '/api/v1/office/templates/instantiate',
    rawBody: true,
    body: (a) => {
      const body: Record<string, unknown> = {
        workspace_path: String(a.workspacePath ?? ''),
        filename: String(a.filename ?? ''),
        data: (a.data as Record<string, string>) ?? {},
      };
      // Exactly one of the two instantiate keys is sent (backend contract).
      if (a.templateId) body.template_id = a.templateId;
      if (a.workspaceTemplate) body.workspace_template = a.workspaceTemplate;
      if (a.images && Object.keys(a.images as Record<string, string>).length > 0) {
        body.images = a.images;
      }
      return body;
    },
  },

  // Journal template subsystem (Task 7, 2026-09-10). 5 routes for
  // backend/api/office_routes.py::journal_router (mounted at
  // /api/v1/office/journal/*). The renderer parses a .docx template into
  // a structured JournalSpec, lists saved specs, fetches one by id,
  // validates a written paper against a spec, and fills a paper from
  // structured content.
  office_journal_parse_template: {
    method: 'POST',
    path: () => `/api/v1/office/journal/parse-template`,
    body: (a) => ({ file_path: String((a as { file_path: string }).file_path) }),
  },
  office_journal_list_specs: {
    method: 'GET',
    path: () => `/api/v1/office/journal/specs`,
  },
  office_journal_get_spec: {
    method: 'GET',
    path: (a) =>
      `/api/v1/office/journal/specs/${encodeURIComponent(String((a as { spec_id: string }).spec_id))}`,
  },
  office_journal_validate: {
    method: 'POST',
    path: () => `/api/v1/office/journal/validate`,
    body: (a) => {
      const req = a as { spec_id?: string; file_path?: string };
      return { spec_id: req.spec_id, file_path: req.file_path };
    },
  },
  office_journal_fill_from_content: {
    method: 'POST',
    path: () => `/api/v1/office/journal/fill-from-content`,
    body: (a) => a as Record<string, unknown>,
  },
};
