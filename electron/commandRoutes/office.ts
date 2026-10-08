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
};
