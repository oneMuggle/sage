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

  // M2c (2026-11-01): Word rule-pack audit/fix surface.
  // GET query strings are not auto-translated by the bridge — serialize workspacePath here.
  // The audit/fix POST bodies use rawBody because nested rule `params` keys are user data and
  // must never be camelCase-rewritten.
  office_word_rulepacks_list: {
    method: 'GET',
    path: (a) => {
      const ws = a.workspacePath ?? a.workspace_path;
      return `/api/v1/office/word/rulepacks${ws ? `?workspace_path=${encodeURIComponent(String(ws))}` : ''}`;
    },
  },
  office_word_rulepack_get: {
    method: 'GET',
    path: (a) => {
      const ws = a.workspacePath ?? a.workspace_path;
      const base = `/api/v1/office/word/rulepacks/${encodeURIComponent(String(a.packId ?? a.pack_id))}`;
      return ws ? `${base}?workspace_path=${encodeURIComponent(String(ws))}` : base;
    },
  },
  office_word_audit: {
    method: 'POST',
    path: () => '/api/v1/office/word/audit',
    rawBody: true,
    body: (a) => ({
      workspace_path: a.workspacePath ?? a.workspace_path,
      file_path: a.filePath ?? a.file_path,
      ...((a.rulepackId ?? a.rulepack_id) ? { rulepack_id: a.rulepackId ?? a.rulepack_id } : {}),
      ...((a.maxSizeBytes ?? a.max_size_bytes)
        ? { max_size_bytes: a.maxSizeBytes ?? a.max_size_bytes }
        : {}),
    }),
  },
  office_word_audit_fix: {
    method: 'POST',
    path: () => '/api/v1/office/word/audit/fix',
    rawBody: true,
    body: (a) => ({
      workspace_path: a.workspacePath ?? a.workspace_path,
      file_path: a.filePath ?? a.file_path,
      ...((a.rulepackId ?? a.rulepack_id) ? { rulepack_id: a.rulepackId ?? a.rulepack_id } : {}),
      ...((a.outputFilename ?? a.output_filename)
        ? { output_filename: a.outputFilename ?? a.output_filename }
        : {}),
      overwrite: Boolean(a.overwrite),
      ...((a.maxSizeBytes ?? a.max_size_bytes)
        ? { max_size_bytes: a.maxSizeBytes ?? a.max_size_bytes }
        : {}),
    }),
  },
  // M3c: rule extraction from spec/template documents. rawBody keeps the
  // nested rule-pack params untouched on save.
  office_word_rulepacks_extract: {
    method: 'POST',
    path: () => '/api/v1/office/word/rulepacks/extract',
    rawBody: true,
    body: (a) => ({
      workspace_path: a.workspacePath ?? a.workspace_path,
      file_path: a.filePath ?? a.file_path,
      file_type: a.fileType ?? a.file_type ?? 'spec',
      ...((a.packId ?? a.pack_id) ? { pack_id: a.packId ?? a.pack_id } : {}),
      ...((a.packName ?? a.pack_name) ? { pack_name: a.packName ?? a.pack_name } : {}),
      use_llm: Boolean(a.useLlm ?? a.use_llm),
      ...((a.maxSizeBytes ?? a.max_size_bytes)
        ? { max_size_bytes: a.maxSizeBytes ?? a.max_size_bytes }
        : {}),
    }),
  },
  office_word_rulepacks_extract_save: {
    method: 'POST',
    path: () => '/api/v1/office/word/rulepacks/extract/save',
    rawBody: true,
    body: (a) => ({
      workspace_path: a.workspacePath ?? a.workspace_path,
      pack: a.pack,
    }),
  },
  // M2.5 (2026-11-05): 格式规范书库（CRUD/提取/激活/绑定）。
  // GET/DELETE 的 query 不经过桥自动翻译 —— workspace_path 在此手工序列化；
  // 带 pack 的 POST/PATCH 用 rawBody，保持嵌套规则 params 的用户数据原样。
  office_specs_list: {
    method: 'GET',
    path: (a) => {
      const ws = a.workspacePath ?? a.workspace_path;
      return `/api/v1/office/specs${ws ? `?workspace_path=${encodeURIComponent(String(ws))}` : ''}`;
    },
  },
  office_specs_get: {
    method: 'GET',
    path: (a) => {
      const ws = a.workspacePath ?? a.workspace_path;
      const base = `/api/v1/office/specs/${encodeURIComponent(String(a.specId ?? a.spec_id))}`;
      return ws ? `${base}?workspace_path=${encodeURIComponent(String(ws))}` : base;
    },
  },
  office_specs_create: {
    method: 'POST',
    path: () => '/api/v1/office/specs',
    rawBody: true,
    body: (a) => ({
      workspace_path: a.workspacePath ?? a.workspace_path,
      name: a.name,
      ...(a.pack ? { pack: a.pack } : {}),
      ...((a.rulepackId ?? a.rulepack_id)
        ? { rulepack_id: a.rulepackId ?? a.rulepack_id }
        : {}),
      ...((a.sourceFilePath ?? a.source_file_path)
        ? { source_file_path: a.sourceFilePath ?? a.source_file_path }
        : {}),
      ...((a.sourceContentHash ?? a.source_content_hash)
        ? { source_content_hash: a.sourceContentHash ?? a.source_content_hash }
        : {}),
      is_default: Boolean(a.isDefault ?? a.is_default),
    }),
  },
  office_specs_update: {
    method: 'PATCH',
    path: (a) =>
      `/api/v1/office/specs/${encodeURIComponent(String(a.specId ?? a.spec_id))}`,
    rawBody: true,
    body: (a) => ({
      workspace_path: a.workspacePath ?? a.workspace_path,
      ...(a.name !== undefined ? { name: a.name } : {}),
      ...(a.pack ? { pack: a.pack } : {}),
      ...((a.sourceFilePath ?? a.source_file_path) !== undefined
        ? { source_file_path: a.sourceFilePath ?? a.source_file_path }
        : {}),
      ...((a.sourceContentHash ?? a.source_content_hash) !== undefined
        ? { source_content_hash: a.sourceContentHash ?? a.source_content_hash }
        : {}),
    }),
  },
  office_specs_delete: {
    method: 'DELETE',
    path: (a) => {
      const ws = a.workspacePath ?? a.workspace_path;
      return `/api/v1/office/specs/${encodeURIComponent(String(a.specId ?? a.spec_id))}?workspace_path=${encodeURIComponent(String(ws))}`;
    },
  },
  office_specs_extract: {
    method: 'POST',
    path: () => '/api/v1/office/specs/extract',
    rawBody: true,
    body: (a) => ({
      workspace_path: a.workspacePath ?? a.workspace_path,
      file_path: a.filePath ?? a.file_path,
      ...((a.packId ?? a.pack_id) ? { pack_id: a.packId ?? a.pack_id } : {}),
      ...((a.packName ?? a.pack_name) ? { pack_name: a.packName ?? a.pack_name } : {}),
      use_llm: Boolean(a.useLlm ?? a.use_llm),
      ...((a.maxSizeBytes ?? a.max_size_bytes)
        ? { max_size_bytes: a.maxSizeBytes ?? a.max_size_bytes }
        : {}),
    }),
  },
  office_specs_activate: {
    method: 'POST',
    path: (a) =>
      `/api/v1/office/specs/${encodeURIComponent(String(a.specId ?? a.spec_id))}/activate`,
    body: (a) => ({
      workspace_path: a.workspacePath ?? a.workspace_path,
    }),
  },
  office_specs_clear_default: {
    method: 'DELETE',
    path: (a) => {
      const ws = a.workspacePath ?? a.workspace_path;
      return `/api/v1/office/specs/default?workspace_path=${encodeURIComponent(String(ws))}`;
    },
  },
  office_doc_spec_get: {
    method: 'GET',
    path: (a) => {
      const ws = a.workspacePath ?? a.workspace_path;
      return `/api/v1/office/doc/${encodeURIComponent(String(a.docId ?? a.doc_id))}/spec?workspace_path=${encodeURIComponent(String(ws))}`;
    },
  },
  office_doc_spec_bind: {
    method: 'POST',
    path: (a) =>
      `/api/v1/office/doc/${encodeURIComponent(String(a.docId ?? a.doc_id))}/spec`,
    body: (a) => ({
      workspace_path: a.workspacePath ?? a.workspace_path,
      spec_id: a.specId ?? a.spec_id ?? null,
    }),
  },
  // M3 (2026-11-05): 「规范书规则 + LLM」合并审校 + 历史。审校请求体
  // snake_case 直传；历史为只读 GET。
  office_ai_review: {
    method: 'POST',
    path: () => '/api/v1/office/ai/review',
    body: (a) => ({
      workspace_path: a.workspacePath ?? a.workspace_path,
      file_path: a.filePath ?? a.file_path,
      ...((a.docId ?? a.doc_id) ? { doc_id: a.docId ?? a.doc_id } : {}),
      ...((a.specId ?? a.spec_id) ? { spec_id: a.specId ?? a.spec_id } : {}),
      ...(a.scope ? { scope: a.scope } : {}),
      use_llm: a.useLlm !== false,
      ...((a.maxIssues ?? a.max_issues)
        ? { max_issues: a.maxIssues ?? a.max_issues }
        : {}),
      ...((a.maxSizeBytes ?? a.max_size_bytes)
        ? { max_size_bytes: a.maxSizeBytes ?? a.max_size_bytes }
        : {}),
    }),
  },
  office_doc_ai_reviews: {
    method: 'GET',
    path: (a) => {
      const params = new URLSearchParams();
      const ws = a.workspacePath ?? a.workspace_path;
      if (ws) params.set('workspace_path', String(ws));
      if (a.limit) params.set('limit', String(a.limit));
      const qs = params.toString();
      return `/api/v1/office/doc/${encodeURIComponent(String(a.docId ?? a.doc_id))}/ai-reviews${qs ? `?${qs}` : ''}`;
    },
  },
  // M4c: native tracked revisions (w:ins/w:del + comments). rawBody keeps
  // explicit change payloads and nested rule-pack params untouched.
  office_word_revise: {
    method: 'POST',
    path: () => '/api/v1/office/word/audit/revise',
    rawBody: true,
    body: (a) => ({
      workspace_path: a.workspacePath ?? a.workspace_path,
      file_path: a.filePath ?? a.file_path,
      ...((a.rulepackId ?? a.rulepack_id) ? { rulepack_id: a.rulepackId ?? a.rulepack_id } : {}),
      ...(Array.isArray(a.changes) ? { changes: a.changes } : {}),
      ...((a.outputFilename ?? a.output_filename)
        ? { output_filename: a.outputFilename ?? a.output_filename }
        : {}),
      overwrite: Boolean(a.overwrite),
      author: a.author ?? 'Sage',
      add_comments: a.addComments ?? a.add_comments ?? true,
      ...((a.maxSizeBytes ?? a.max_size_bytes)
        ? { max_size_bytes: a.maxSizeBytes ?? a.max_size_bytes }
        : {}),
    }),
  },
  // M5c (2026-11-02): render-level audit + workspace batch audit surface.
  // rawBody: margins_cm is keyed by side (top/bottom/left/right) and
  // rulepack.params by rule-specific keys — both are user data the generic
  // camelCase pass must not rewrite.
  office_word_audit_render: {
    method: 'POST',
    path: () => '/api/v1/office/word/audit/render',
    rawBody: true,
    body: (a) => ({
      workspace_path: a.workspacePath ?? a.workspace_path,
      file_path: a.filePath ?? a.file_path,
      ...((a.expectedSize ?? a.expected_size)
        ? { expected_size: a.expectedSize ?? a.expected_size }
        : {}),
      ...(a.marginsCm ?? a.margins_cm ? { margins_cm: a.marginsCm ?? a.margins_cm } : {}),
      ...(Array.isArray(a.allowedFonts ?? a.allowed_fonts)
        ? { allowed_fonts: a.allowedFonts ?? a.allowed_fonts }
        : {}),
      require_page_number: Boolean(a.requirePageNumber ?? a.require_page_number),
      ...((a.marginToleranceCm ?? a.margin_tolerance_cm) !== undefined
        ? { margin_tolerance_cm: a.marginToleranceCm ?? a.margin_tolerance_cm }
        : {}),
      ...((a.pageNumberBand ?? a.page_number_band) !== undefined
        ? { page_number_band: a.pageNumberBand ?? a.page_number_band }
        : {}),
      ...((a.timeoutSeconds ?? a.timeout_seconds) !== undefined
        ? { timeout_seconds: a.timeoutSeconds ?? a.timeout_seconds }
        : {}),
      ...((a.maxSizeBytes ?? a.max_size_bytes)
        ? { max_size_bytes: a.maxSizeBytes ?? a.max_size_bytes }
        : {}),
    }),
  },
  office_word_audit_batch: {
    method: 'POST',
    path: () => '/api/v1/office/word/audit/batch',
    rawBody: true,
    body: (a) => ({
      workspace_path: a.workspacePath ?? a.workspace_path,
      ...(Array.isArray(a.filePaths ?? a.file_paths)
        ? { file_paths: a.filePaths ?? a.file_paths }
        : {}),
      ...(a.pattern ? { pattern: a.pattern } : {}),
      ...(a.maxFiles ?? a.max_files ? { max_files: a.maxFiles ?? a.max_files } : {}),
      ...((a.rulepackId ?? a.rulepack_id) ? { rulepack_id: a.rulepackId ?? a.rulepack_id } : {}),
      ...(a.rulepack ? { rulepack: a.rulepack } : {}),
      include_report: a.includeReport ?? a.include_report ?? true,
      ...((a.maxSizeBytes ?? a.max_size_bytes)
        ? { max_size_bytes: a.maxSizeBytes ?? a.max_size_bytes }
        : {}),
    }),
  },
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
  // Import duplicate detection (AI workbench, Phase 0). The renderer asks
  // "which imported documents hold the same bytes as the file I am about to
  // import?" and offers the user 打开已有 / 新版本 / 副本.
  // OfficeDuplicateCheckRequest is extra="forbid" — send ONLY workspace_path +
  // file_paths, spelled out snake_case (rawBody skips the camelCase pass).
  office_check_duplicates: {
    method: 'POST',
    path: () => '/api/v1/office/documents/duplicates',
    rawBody: true,
    body: (a) => {
      const requested = a.filePaths ?? a.file_paths;
      return {
        workspace_path: String(a.workspacePath ?? a.workspace_path ?? ''),
        file_paths: Array.isArray(requested) ? requested.map((p) => String(p)) : [],
      };
    },
  },
  // Lineage write-back for the "import as a new version" branch of the
  // duplicate dialog: the new document keeps its own bytes but points at the
  // document it supersedes (office_documents.derived_from).
  office_set_document_lineage: {
    method: 'POST',
    path: (a) =>
      `/api/v1/office/documents/${encodeURIComponent(String(a.docId ?? a.doc_id))}/lineage`,
    rawBody: true,
    body: (a) => ({
      derived_from: (a.derivedFrom ?? a.derived_from ?? null) as string | null,
    }),
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
