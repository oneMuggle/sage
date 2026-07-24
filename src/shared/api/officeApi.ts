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
  OfficeDeleteResponse,
  OfficeDocumentListResponse,
  OfficeExcelGenerateRequest,
  OfficeExcelReadResult,
  OfficePptGenerateRequest,
  OfficePptReadResult,
  OfficeReadRequest,
  OfficeWordGenerateRequest,
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
   * List all office documents in a workspace.
   *
   * Bounded retry is retained here — list is read-only and idempotent,
   * so transient network failures can be safely retried without risk
   * to the user's data.
   */
  async listDocuments(workspacePath: string): Promise<OfficeDocumentListResponse> {
    return withRetry(async () => {
      try {
        return await invoke<OfficeDocumentListResponse>('office_list_documents', {
          workspacePath,
        });
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },

  /**
   * Delete an office document record by id (does not delete the file itself).
   *
   * No retry — kept unreachable from the M0 management view (M3–M5 will
   * wire archive/restore with a user confirmation flow). Exposed here
   * only for legacy callers that explicitly opt in.
   */
  async deleteDocument(docId: string): Promise<OfficeDeleteResponse> {
    try {
      return await invoke<OfficeDeleteResponse>('office_delete_document', { docId });
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
  async generatePpt(req: OfficePptGenerateRequest): Promise<{ output_path: string; filename: string; file_size_bytes: number }> {
    try {
      return await invoke('office_ppt_generate', {
        workspacePath: req.workspace_path,
        filename: req.filename,
        slides: req.slides,
        template: req.template,
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
  async generateWord(req: OfficeWordGenerateRequest): Promise<{ output_path: string; filename: string; file_size_bytes: number }> {
    try {
      return await invoke('office_word_generate', {
        workspacePath: req.workspace_path,
        filename: req.filename,
        title: req.title,
        paragraphs: req.paragraphs,
        tables: req.tables,
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
  async generateExcel(req: OfficeExcelGenerateRequest): Promise<{ output_path: string; filename: string; file_size_bytes: number }> {
    try {
      return await invoke('office_excel_generate', {
        workspacePath: req.workspace_path,
        filename: req.filename,
        sheets: req.sheets,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },
};
