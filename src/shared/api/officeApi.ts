/**
 * Sage API - Office document API (Phase 1.3, plan §4.1.3 step 12)
 *
 * Backend counterpart: backend/api/office_routes.py (mounted at /api/v1/office).
 * Frontend never calls HTTP directly — it uses IPC bridge via invoke().
 */

import { invoke } from './desktopInvoke';
import type {
  OfficeDeleteResponse,
  OfficeDocumentListResponse,
  OfficeExcelReadResult,
  OfficePptReadResult,
  OfficeReadRequest,
  OfficeWordReadResult,
} from './types';
import { handleApiError, withRetry } from './utils';

export const officeApi = {
  /**
   * Read a .pptx file → OfficePptReadResult (slides + summary).
   */
  async readPpt(req: OfficeReadRequest): Promise<OfficePptReadResult> {
    return withRetry(async () => {
      try {
        return await invoke<OfficePptReadResult>('office_ppt_read', {
          workspacePath: req.workspace_path,
          filePath: req.file_path,
          maxSizeBytes: req.max_size_bytes,
        });
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },

  /**
   * Read a .docx file → OfficeWordReadResult (paragraphs + tables + summary).
   */
  async readWord(req: OfficeReadRequest): Promise<OfficeWordReadResult> {
    return withRetry(async () => {
      try {
        return await invoke<OfficeWordReadResult>('office_word_read', {
          workspacePath: req.workspace_path,
          filePath: req.file_path,
          maxSizeBytes: req.max_size_bytes,
        });
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },

  /**
   * Read a .xlsx file → OfficeExcelReadResult (sheets + summary).
   */
  async readExcel(req: OfficeReadRequest): Promise<OfficeExcelReadResult> {
    return withRetry(async () => {
      try {
        return await invoke<OfficeExcelReadResult>('office_excel_read', {
          workspacePath: req.workspace_path,
          filePath: req.file_path,
          maxSizeBytes: req.max_size_bytes,
        });
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },

  /**
   * List all office documents in a workspace.
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
   */
  async deleteDocument(docId: string): Promise<OfficeDeleteResponse> {
    return withRetry(async () => {
      try {
        return await invoke<OfficeDeleteResponse>('office_delete_document', { docId });
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },
};
