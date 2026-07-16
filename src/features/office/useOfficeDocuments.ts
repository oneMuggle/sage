/**
 * useOfficeDocuments — React hook for the /office page (Phase 1.3, plan §4.1.4 step 15).
 *
 * Provides:
 * - documents: workspace's office document list
 * - loading / error state
 * - readPpt / readWord / readExcel: invoke backend read endpoint
 * - deleteDocument: invoke backend delete endpoint
 * - refresh: re-fetch documents list
 *
 * State management: local React useState (no global store needed — the
 * /office page is single-instance and documents are scoped to a workspace).
 */

import { useCallback, useEffect, useState } from 'react';

import { officeApi } from '../../shared/api/officeApi';
import type {
  OfficeDocumentSummary,
  OfficeExcelReadResult,
  OfficePptReadResult,
  OfficeWordReadResult,
} from '../../shared/api/types';

export interface UseOfficeDocumentsReturn {
  documents: OfficeDocumentSummary[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  readPpt: (filePath: string) => Promise<OfficePptReadResult>;
  readWord: (filePath: string) => Promise<OfficeWordReadResult>;
  readExcel: (filePath: string) => Promise<OfficeExcelReadResult>;
  deleteDocument: (docId: string) => Promise<void>;
}

/**
 * Hook for the /office page.
 *
 * @param workspacePath - user's selected workspace directory. Pass null when
 *                       no workspace is selected (loading stays true, list empty).
 */
export function useOfficeDocuments(workspacePath: string | null): UseOfficeDocumentsReturn {
  const [documents, setDocuments] = useState<OfficeDocumentSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!workspacePath) {
      setDocuments([]);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const result = await officeApi.listDocuments(workspacePath);
      setDocuments(result.documents);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setDocuments([]);
    } finally {
      setLoading(false);
    }
  }, [workspacePath]);

  // Auto-refresh when workspacePath changes
  useEffect(() => {
    void refresh();
  }, [refresh]);

  const readPpt = useCallback(
    async (filePath: string): Promise<OfficePptReadResult> => {
      if (!workspacePath) {
        throw new Error('No workspace selected');
      }
      return officeApi.readPpt({ workspace_path: workspacePath, file_path: filePath });
    },
    [workspacePath],
  );

  const readWord = useCallback(
    async (filePath: string): Promise<OfficeWordReadResult> => {
      if (!workspacePath) {
        throw new Error('No workspace selected');
      }
      return officeApi.readWord({ workspace_path: workspacePath, file_path: filePath });
    },
    [workspacePath],
  );

  const readExcel = useCallback(
    async (filePath: string): Promise<OfficeExcelReadResult> => {
      if (!workspacePath) {
        throw new Error('No workspace selected');
      }
      return officeApi.readExcel({ workspace_path: workspacePath, file_path: filePath });
    },
    [workspacePath],
  );

  const deleteDocument = useCallback(async (docId: string): Promise<void> => {
    // HIGH FIX (Phase 2 — real implementation): optimistic update with
    // rollback. Previous commit claimed this fix but never modified the
    // file (linter or stale write). Now correctly:
    // 1. Capture the doc for potential rollback
    // 2. Optimistically remove from list
    // 3. Call API
    // 4. On failure, restore the doc to the front of the list (matches
    //    list_documents ORDER BY created_at DESC)
    const previous = documents.find((d) => d.id === docId);
    if (!previous) {
      // Nothing to do; not in local cache
      return;
    }
    setDocuments((prev) => prev.filter((d) => d.id !== docId));
    try {
      await officeApi.deleteDocument(docId);
    } catch (err) {
      // Roll back: re-insert at head (most recent first).
      setDocuments((prev) => {
        if (prev.some((d) => d.id === docId)) return prev;
        return [previous, ...prev];
      });
      throw err;
    }
  }, [documents]);

  return {
    documents,
    loading,
    error,
    refresh,
    readPpt,
    readWord,
    readExcel,
    deleteDocument,
  };
}
