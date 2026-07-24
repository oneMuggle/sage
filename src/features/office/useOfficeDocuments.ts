/**
 * useOfficeDocuments — React hook for the /office page (Phase 1.3, plan §4.1.4 step 15).
 *
 * Provides:
 * - documents: workspace's office document list
 * - loading / error state
 * - importAndRead: pick (or drop) → import → read → complete-or-discard
 * - saveAs / open / showInFolder: native gateway actions via the
 *   Electron managed-file bridge (M0 Task 5)
 * - refresh: re-fetch documents list
 *
 * M0 Task 6 (2026-07-23): the hook now owns the import-token lifecycle.
 * `importAndRead` always calls `completeOfficeImport` on a successful
 * read or `discardOfficeImport` on a parse failure. The render no
 * longer touches `withRetry` — that decision lives in `officeApi.ts`,
 * where read/generate/delete are NOT retried (`utils.withRetry` is
 * retained only for idempotent listing).
 *
 * State management: local React useState (no global store needed — the
 * /office page is single-instance and documents are scoped to a workspace).
 */

import { useCallback, useEffect, useState } from 'react';

import { officeApi } from '../../shared/api/officeApi';
import type {
  OfficeDocType,
  OfficeDocumentSummary,
  OfficeExcelReadResult,
  OfficePptReadResult,
  OfficeWordReadResult,
} from '../../shared/api/types';

/** Read result union — OfficePreviewPanel is doc-type-agnostic. */
export type OfficeReadResult =
  | OfficePptReadResult
  | OfficeWordReadResult
  | OfficeExcelReadResult;

export interface UseOfficeDocumentsReturn {
  documents: OfficeDocumentSummary[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  /**
   * Pick a file via the native dialog, import it into the managed
   * directory, run the type-specific read, then call
   * `completeOfficeImport` on success or `discardOfficeImport` on
   * failure. Returns the read result.
   *
   * Cancellation: returns `null` if the user cancels the dialog.
   */
  importAndRead: (docType: OfficeDocType) => Promise<OfficeReadResult | null>;
  /**
   * Drag-and-drop variant: caller already has the sourcePath. Same
   * import + read + complete/discard lifecycle as `importAndRead`.
   */
  readDropped: (docType: OfficeDocType, sourcePath: string) => Promise<OfficeReadResult>;
  /**
   * Native Save As dialog → copy managed → chosen path. Uses the
   * gateway bridge; the renderer cannot supply a destination path.
   */
  saveAs: (docId: string) => Promise<string | null>;
  /**
   * shell.openPath on the managed file. Reconstructed server-side
   * from the document record; the renderer cannot supply a path.
   */
  open: (docId: string) => Promise<void>;
  /**
   * shell.showItemInFolder on the managed file.
   */
  showInFolder: (docId: string) => Promise<void>;
  /**
   * Read-only access to the workspace documents for callers that need
   * to reconstruct an `OfficeManagedRef` from the document ID.
   */
  findDocument: (docId: string) => OfficeDocumentSummary | undefined;
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

  const findDocument = useCallback(
    (docId: string) => documents.find((d) => d.id === docId),
    [documents],
  );

  const readByType = useCallback(
    async (docType: OfficeDocType, managedPath: string): Promise<OfficeReadResult> => {
      if (!workspacePath) throw new Error('No workspace selected');
      if (docType === 'ppt') {
        return officeApi.readPpt({ workspace_path: workspacePath, file_path: managedPath });
      }
      if (docType === 'word') {
        return officeApi.readWord({ workspace_path: workspacePath, file_path: managedPath });
      }
      return officeApi.readExcel({ workspace_path: workspacePath, file_path: managedPath });
    },
    [workspacePath],
  );

  const safeDiscard = useCallback(async (importToken: string) => {
    try {
      await window.electronAPI?.office.discardOfficeImport(importToken);
    } catch {
      // Best-effort: a failed discard just leaves the staging file on
      // disk. The next pick-and-import uses a fresh token, so the
      // orphan is bounded.
    }
  }, []);

  const importAndRead = useCallback(
    async (docType: OfficeDocType): Promise<OfficeReadResult | null> => {
      if (!workspacePath) {
        throw new Error('No workspace selected');
      }
      const imported = await window.electronAPI?.office.pickAndImportOfficeFile(
        workspacePath,
        docType,
      );
      if (!imported) return null; // user cancelled
      try {
        const result = await readByType(docType, imported.managedPath);
        // Read succeeded → finalize the import; the staging file is
        // now permanent and the token is consumed.
        await window.electronAPI?.office.completeOfficeImport(imported.importToken);
        return result;
      } catch (e) {
        // Read failed → discard the staging file so we don't leak
        // half-imported bytes onto disk.
        await safeDiscard(imported.importToken);
        throw e;
      }
    },
    [workspacePath, readByType, safeDiscard],
  );

  const readDropped = useCallback(
    async (docType: OfficeDocType, sourcePath: string): Promise<OfficeReadResult> => {
      if (!workspacePath) {
        throw new Error('No workspace selected');
      }
      const imported = await window.electronAPI?.office.importDroppedOfficeFile(
        workspacePath,
        docType,
        sourcePath,
      );
      if (!imported) {
        throw new Error('importDroppedOfficeFile returned no payload');
      }
      try {
        const result = await readByType(docType, imported.managedPath);
        await window.electronAPI?.office.completeOfficeImport(imported.importToken);
        return result;
      } catch (e) {
        await safeDiscard(imported.importToken);
        throw e;
      }
    },
    [workspacePath, readByType, safeDiscard],
  );

  const saveAs = useCallback(
    async (docId: string): Promise<string | null> => {
      const doc = documents.find((d) => d.id === docId);
      if (!doc || !workspacePath) {
        throw new Error('Document or workspace not found');
      }
      const saved = await window.electronAPI?.office.saveOfficeDocumentAs({
        workspacePath,
        docType: doc.doc_type,
        documentId: doc.id,
        filename: doc.original_filename ?? doc.generated_filename,
      });
      return saved?.savedPath ?? null;
    },
    [documents, workspacePath],
  );

  const open = useCallback(
    async (docId: string): Promise<void> => {
      const doc = documents.find((d) => d.id === docId);
      if (!doc || !workspacePath) {
        throw new Error('Document or workspace not found');
      }
      await window.electronAPI?.office.openOfficeDocument({
        workspacePath,
        docType: doc.doc_type,
        documentId: doc.id,
        filename: doc.original_filename ?? doc.generated_filename,
      });
    },
    [documents, workspacePath],
  );

  const showInFolder = useCallback(
    async (docId: string): Promise<void> => {
      const doc = documents.find((d) => d.id === docId);
      if (!doc || !workspacePath) {
        throw new Error('Document or workspace not found');
      }
      await window.electronAPI?.office.showOfficeDocumentInFolder({
        workspacePath,
        docType: doc.doc_type,
        documentId: doc.id,
        filename: doc.original_filename ?? doc.generated_filename,
      });
    },
    [documents, workspacePath],
  );

  return {
    documents,
    loading,
    error,
    refresh,
    importAndRead,
    readDropped,
    saveAs,
    open,
    showInFolder,
    findDocument,
  };
}
