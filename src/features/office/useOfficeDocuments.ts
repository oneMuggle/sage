/**
 * useOfficeDocuments — React hook for the /office page (Phase 1.3, plan §4.1.4 step 15).
 *
 * Provides:
 * - documents: workspace's office document list
 * - loading / error state
 * - importAndRead: pick (or drop) → import → read → complete-or-discard
 * - saveAs / open / showInFolder: native gateway actions via the
 *   Electron managed-file bridge (M0 Task 5)
 * - archiveDocument / restoreDocument + view toggle: soft-delete
 *   lifecycle (parity batch 1, item 1.7)
 * - batchArchive / batchRestore: sequential multi-doc archive/restore
 *   with ONE refetch and a per-item success/failure split (round-3 N5)
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

import { useCallback, useEffect, useRef, useState } from 'react';

import { officeApi } from '../../shared/api/officeApi';
import type {
  OfficeDocType,
  OfficeDocumentSummary,
  OfficeDuplicateCheckEntry,
  OfficeDuplicateGroup,
  OfficeExcelReadResult,
  OfficePdfReadResult,
  OfficePptReadResult,
  OfficeWordReadResult,
} from '../../shared/api/types';

import type { OfficeBatchResult } from './OfficeDocumentList';
import { importOfficeByType, readStagedOfficeFile } from './importOfficeReference';

/**
 * The duplicate-check route caps one request at 50 files; larger import
 * batches are checked in chunks of this size (mirrors
 * `MAX_DUPLICATE_CHECK_FILES` in backend/api/office_dedup_routes.py).
 */
const DUPLICATE_CHECK_CHUNK = 50;

/** Read result union — OfficePreviewPanel is doc-type-agnostic. */
export type OfficeReadResult =
  | OfficePptReadResult
  | OfficeWordReadResult
  | OfficeExcelReadResult
  | OfficePdfReadResult;

/**
 * One successfully imported + parsed file in a multi-file batch.
 */
export interface OfficeMultiImportEntry {
  /** Managed docId (from the gateway's `documentId`). */
  documentId: string;
  /** Doc type resolved by the main process from the file extension. */
  docType: OfficeDocType;
  /** Original filename — for display in the skipped/summary toast. */
  filename: string;
  /** Parsed read result. */
  readResult: OfficeReadResult;
}

/**
 * A file the batch could NOT import. `reason` distinguishes:
 *   - `unsupported-extension`  — the extension is not a known Office type
 *   - `staging-failed`         — the managed copy could not be written
 *   - `read-failed`            — staging worked but the parser rejected it
 *   - `duplicate-open-existing` — the user chose to open the existing
 *                                document instead of importing a copy
 */
export interface OfficeMultiImportSkipped {
  filename: string;
  reason: 'unsupported-extension' | 'staging-failed' | 'read-failed' | 'duplicate-open-existing';
  message?: string;
}

/**
 * What the user can do about an import whose bytes match an existing
 * document (AI workbench, Phase 0).
 */
export type OfficeDuplicateChoice = 'open-existing' | 'new-version' | 'keep-copy';

/**
 * A staged file waiting for the duplicate decision. `duplicates[0]` is the
 * oldest existing document holding the same bytes — the one the dialog
 * offers to open.
 */
export interface OfficePendingDuplicate {
  /** Staged file's display name (original when known). */
  filename: string;
  /** Live documents that hold the same bytes, oldest first. */
  duplicates: OfficeDocumentSummary[];
  /** `sha256:<64 hex>` digest shared by the staged file and duplicates. */
  contentHash: string | null;
}

/**
 * Outcome of a unified (multi-file) import. `imported` and `skipped`
 * together account for every file the user handed over — nothing is
 * silently dropped. `openedExisting` lists the documents the user chose
 * to open instead of importing a duplicate.
 */
export interface OfficeMultiImportResult {
  imported: OfficeMultiImportEntry[];
  skipped: OfficeMultiImportSkipped[];
  openedExisting: OfficeDocumentSummary[];
}

/** Which slice of the document lifecycle the list renders (item 1.7). */
export type OfficeListView = 'live' | 'archived';

export interface UseOfficeDocumentsReturn {
  documents: OfficeDocumentSummary[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  /**
   * Which lifecycle slice `documents` renders (item 1.7). `'live'` is the
   * default list (backend hides archived rows); `'archived'` fetches with
   * include_archived and keeps only soft-deleted rows.
   */
  view: OfficeListView;
  setView: (view: OfficeListView) => void;
  /**
   * Phase 1 Item A: search/filter/sort state — driven from the document
   * library's toolbar and forwarded server-side on every fetch. All
   * three setters trigger a refetch (the effect below depends on them).
   *
   *   - `q`: substring match on original/generated filename
   *   - `docType`: restrict to a single Office doc type (empty = all)
   *   - `sort`: `updated_at` / `-updated_at` / `name` / `-name` / `size` / `-size`
   */
  q: string;
  setQ: (value: string) => void;
  docType: string;
  setDocType: (value: string) => void;
  sort: string;
  setSort: (value: string) => void;
  /**
   * Phase 1 Item A: live documents grouped by content hash. Populated
   * by `loadDuplicateGroups()` for the `'live'` view and empty for
   * `'archived'`. Used by the list component to render the "重复" badge
   * and to drive the "archive all but newest" cleanup.
   */
  duplicateGroups: OfficeDuplicateGroup[];
  loadDuplicateGroups: () => Promise<void>;
  /**
   * Archive every group member except the newest one. Resolves with
   * the per-doc archive outcome; the caller drives the toast.
   */
  archiveAllButNewest: (group: OfficeDuplicateGroup) => Promise<OfficeBatchResult>;
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
   * Unified (multi-file) import via the native dialog: ONE dialog for
   * every supported Office extension, `multiSelections` enabled. The
   * Electron main process resolves each file's docType from its
   * extension, stages it, and reports the files it could not stage.
   *
   * Cancellation: returns `null` if the user cancels the dialog.
   */
  importAndReadMulti: () => Promise<OfficeMultiImportResult | null>;
  /**
   * Drag-and-drop variant of `importAndReadMulti`: the caller already
   * has the OS source paths of the dropped files. Same per-file
   * lifecycle (legacy convert → read → complete/discard).
   */
  readDroppedMulti: (sourcePaths: string[]) => Promise<OfficeMultiImportResult>;
  /**
   * The staged file currently waiting for a duplicate decision, or null
   * when the batch is not paused. While non-null the import promise is
   * pending — `OfficeDuplicateDialog` renders this and calls
   * `resolvePendingDuplicate` when the user picks an action.
   */
  pendingDuplicate: OfficePendingDuplicate | null;
  /**
   * Resolve the paused import with the user's choice:
   *   - `open-existing` — drop the staged copy, preview the existing doc
   *   - `new-version`   — import, then link the new doc to the existing one
   *   - `keep-copy`     — import as an independent copy
   */
  resolvePendingDuplicate: (choice: OfficeDuplicateChoice) => void;
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
   * Archive (soft-delete) a document, then re-fetch the current view.
   * The row hides from the live list but stays recoverable (item 1.7).
   */
  archiveDocument: (docId: string) => Promise<void>;
  /**
   * Restore (un-archive) a document, then re-fetch the current view.
   */
  restoreDocument: (docId: string) => Promise<void>;
  /**
   * Batch-archive the given docs sequentially (round-3 N5), then refetch
   * the current view ONCE for the whole batch. Per-item failures are
   * collected — not thrown — so the caller can report a counted summary
   * toast.
   */
  batchArchive: (docIds: string[]) => Promise<OfficeBatchResult>;
  /**
   * Batch-restore the given docs sequentially; same contract as
   * batchArchive (round-3 N5).
   */
  batchRestore: (docIds: string[]) => Promise<OfficeBatchResult>;
  /**
   * Re-read a document's managed file and return the fresh read result —
   * used after a snapshot restore to refresh the preview (item 1.7).
   */
  readDocument: (docId: string) => Promise<OfficeReadResult>;
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
  // Item 1.7: 'live' (default) vs 'archived' list slice.
  const [view, setView] = useState<OfficeListView>('live');
  // Phase 1 Item A: server-side search / type filter / sort. Empty
  // strings mean "no filter"; every setter triggers a refetch via the
  // effect below (fetchDocuments picks them up as deps).
  const [q, setQ] = useState('');
  const [docType, setDocType] = useState('');
  const [sort, setSort] = useState('-updated_at');
  // Phase 1 Item A: duplicate groups for the live view.
  const [duplicateGroups, setDuplicateGroups] = useState<OfficeDuplicateGroup[]>([]);
  // Phase 0 duplicate gate: the staged file the batch is paused on, plus
  // the resolver that hands the user's choice back to the batch loop.
  const [pendingDuplicate, setPendingDuplicate] = useState<OfficePendingDuplicate | null>(null);
  const duplicateResolverRef = useRef<((choice: OfficeDuplicateChoice) => void) | null>(null);

  const requestDuplicateChoice = useCallback(
    (pending: OfficePendingDuplicate): Promise<OfficeDuplicateChoice> =>
      new Promise<OfficeDuplicateChoice>((resolve) => {
        const previous = duplicateResolverRef.current;
        duplicateResolverRef.current = resolve;
        setPendingDuplicate(pending);
        // Two overlapping batches must not leave the earlier promise
        // dangling — its file imports as an independent copy.
        if (previous) previous('keep-copy');
      }),
    [],
  );

  const resolvePendingDuplicate = useCallback((choice: OfficeDuplicateChoice): void => {
    const resolve = duplicateResolverRef.current;
    duplicateResolverRef.current = null;
    setPendingDuplicate(null);
    if (resolve) resolve(choice);
  }, []);

  // Unmounting mid-batch must not strand the import promise: settle it
  // with the default action so the staged files finish importing.
  useEffect(
    () => () => {
      const resolve = duplicateResolverRef.current;
      duplicateResolverRef.current = null;
      if (resolve) resolve('keep-copy');
    },
    [],
  );

  const fetchDocuments = useCallback(
    async (currentView: OfficeListView): Promise<OfficeDocumentSummary[]> => {
      if (!workspacePath) return [];
      const result = await officeApi.listDocuments(workspacePath, {
        includeArchived: currentView === 'archived',
        q: q || undefined,
        docType: docType || undefined,
        sort: sort || undefined,
      });
      // include_archived=true returns live + archived rows; the archived
      // view only wants the soft-deleted slice.
      if (currentView === 'archived') {
        return result.documents.filter((d) => d.archived_at != null);
      }
      return result.documents;
    },
    [workspacePath, q, docType, sort],
  );

  // Phase 1 Item A: reload duplicate groups whenever the live view is
  // active and any filter changes. Archived view has no duplicate badge.
  const loadDuplicateGroups = useCallback(async () => {
    if (!workspacePath || view !== 'live') {
      setDuplicateGroups([]);
      return;
    }
    try {
      const result = await officeApi.listDuplicateGroups(workspacePath);
      setDuplicateGroups(result.groups);
    } catch {
      // Duplicate grouping is advisory — a failure hides the badge but
      // must not break the document list itself.
      setDuplicateGroups([]);
    }
  }, [workspacePath, view]);

  const refresh = useCallback(async () => {
    if (!workspacePath) {
      setDocuments([]);
      setDuplicateGroups([]);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      setDocuments(await fetchDocuments(view));
      // Duplicate grouping runs in parallel with the list fetch only in
      // the initial effect; here it is sequential because `refresh` is
      // called after mutations that may change both lists.
      if (view === 'live') {
        const result = await officeApi.listDuplicateGroups(workspacePath);
        setDuplicateGroups(result.groups);
      } else {
        setDuplicateGroups([]);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setDocuments([]);
      setDuplicateGroups([]);
    } finally {
      setLoading(false);
    }
  }, [workspacePath, fetchDocuments, view]);

  // Workspace entry is read-only. Filtered views must never drive file deletion.
  // Cancellation guard prevents a stale resolution from a prior
  // workspace from clobbering the new workspace's documents.
  useEffect(() => {
    if (!workspacePath) {
      setDocuments([]);
      setDuplicateGroups([]);
      setLoading(false);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const documents = await fetchDocuments(view);
        if (cancelled) return;
        setDocuments(documents);
        // Duplicate grouping runs alongside the list fetch — both
        // queries target the same workspace so they can share the
        // cancellation guard.
        if (view === 'live') {
          try {
            const result = await officeApi.listDuplicateGroups(workspacePath);
            if (!cancelled) setDuplicateGroups(result.groups);
          } catch {
            // Advisory: a grouping failure must not block the list render.
          }
        } else if (!cancelled) {
          setDuplicateGroups([]);
        }
      } catch (listErr) {
        if (cancelled) return;
        setError(listErr instanceof Error ? listErr.message : String(listErr));
        setDocuments([]);
        setDuplicateGroups([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [workspacePath, fetchDocuments, view]);

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
      if (docType === 'pdf') {
        // PdfReadRequest is extra="forbid" — only the two path fields.
        return officeApi.readPdf({ workspace_path: workspacePath, file_path: managedPath });
      }
      return officeApi.readExcel({ workspace_path: workspacePath, file_path: managedPath });
    },
    [workspacePath],
  );

  const importAndRead = useCallback(
    async (docType: OfficeDocType): Promise<OfficeReadResult | null> => {
      if (!workspacePath) {
        throw new Error('No workspace selected');
      }
      const bridge = window.electronAPI?.office;
      if (!bridge) {
        throw new Error('useOfficeDocuments: electron.office bridge unavailable');
      }
      const imported = await bridge.pickAndImportOfficeFile(workspacePath, docType);
      if (!imported) return null; // user cancelled
      // The staged → read → complete/discard tail is shared with the
      // unified multi-file path via `readStagedOfficeFile`, so both
      // entries own the import token the same way.
      const { readResult } = await readStagedOfficeFile(bridge, workspacePath, {
        documentId: imported.documentId,
        importToken: imported.importToken,
        managedPath: imported.managedPath,
        docType,
        originalName: imported.originalName,
      });
      return readResult;
    },
    [workspacePath],
  );

  const readDropped = useCallback(
    async (docType: OfficeDocType, sourcePath: string): Promise<OfficeReadResult> => {
      if (!workspacePath) {
        throw new Error('No workspace selected');
      }
      // Task 7 (2026-07-26): delegate the import-token lifecycle to the
      // shared helper `importOfficeByType` so /office and chat-read paths
      // stay in lock-step. Behavior is unchanged: read result on success,
      // safeDiscard on read failure.
      const { readResult } = await importOfficeByType(workspacePath, docType, sourcePath);
      return readResult;
    },
    [workspacePath],
  );

  // Phase 0 dedup pre-flight. The backend answers positionally, so entry
  // *i* pairs with staged[i] no matter how it resolves symlinks. Batches
  // are chunked to stay under the route's per-request cap.
  const checkBatchDuplicates = useCallback(
    async (
      wsPath: string,
      staged: ReadonlyArray<{ managedPath: string }>,
    ): Promise<OfficeDuplicateCheckEntry[]> => {
      const checks: OfficeDuplicateCheckEntry[] = [];
      for (let start = 0; start < staged.length; start += DUPLICATE_CHECK_CHUNK) {
        const chunk = staged.slice(start, start + DUPLICATE_CHECK_CHUNK);
        const result = await officeApi.checkDuplicates(
          wsPath,
          chunk.map((file) => file.managedPath),
        );
        checks.push(...result.files);
      }
      return checks;
    },
    [],
  );

  // Phase 0 unified intake: read a batch of ALREADY-STAGED files.
  //
  // The staging half lives in the Electron main process (it resolves the
  // docType from the extension and copies the bytes into the managed
  // directory). This function owns the read half: duplicate gate →
  // legacy conversion → type-specific read → complete/discard, one file
  // at a time.
  //
  // A file that fails to read is reported in `skipped` (reason
  // `read-failed`) rather than aborting the whole batch — one corrupt
  // file must not cost the user the other nine.
  const readStagedBatch = useCallback(
    async (
      wsPath: string,
      staged: ReadonlyArray<{
        documentId: string;
        importToken: string;
        managedPath: string;
        docType: OfficeDocType;
        originalName?: string;
        filename?: string;
      }>,
      skipped: OfficeMultiImportSkipped[],
    ): Promise<OfficeMultiImportResult> => {
      const gateway = window.electronAPI?.office;
      if (!gateway) {
        throw new Error('useOfficeDocuments: electron.office bridge unavailable');
      }
      const duplicateChecks = await checkBatchDuplicates(wsPath, staged);
      const imported: OfficeMultiImportEntry[] = [];
      const openedExisting: OfficeDocumentSummary[] = [];

      for (let index = 0; index < staged.length; index += 1) {
        const file = staged[index];
        const filename = file.originalName ?? file.filename ?? file.managedPath;
        const check = duplicateChecks[index];
        const existing = check?.duplicates[0];
        // Pause on a match until the user picks an action. No match (or
        // no check result) imports straight away as before.
        let choice: OfficeDuplicateChoice = 'keep-copy';
        if (existing) {
          choice = await requestDuplicateChoice({
            filename,
            duplicates: check.duplicates,
            contentHash: check.content_hash,
          });
          if (choice === 'open-existing') {
            openedExisting.push(existing);
            try {
              await gateway.discardOfficeImport(file.importToken);
            } catch {
              // A leaked staging copy is swept up by sweep-orphan-staging;
              // the user's decision to open the existing doc still holds.
            }
            skipped.push({
              filename,
              reason: 'duplicate-open-existing',
              message: existing.original_filename ?? existing.generated_filename,
            });
            continue;
          }
        }
        try {
          const { readResult } = await readStagedOfficeFile(gateway, wsPath, {
            documentId: file.documentId,
            importToken: file.importToken,
            managedPath: file.managedPath,
            docType: file.docType,
            originalName: filename,
          });
          imported.push({
            documentId: file.documentId,
            docType: file.docType,
            filename,
            readResult,
          });
          if (choice === 'new-version' && existing) {
            try {
              await officeApi.setDocumentLineage(file.documentId, existing.id);
            } catch {
              // Lineage is metadata: the import itself succeeded, so a
              // linking failure must not turn it into a failed file.
            }
          }
        } catch (e) {
          skipped.push({
            filename,
            reason: 'read-failed',
            message: e instanceof Error ? e.message : String(e),
          });
        }
      }
      return { imported, skipped, openedExisting };
    },
    [checkBatchDuplicates, requestDuplicateChoice],
  );

  const importAndReadMulti = useCallback(async (): Promise<OfficeMultiImportResult | null> => {
    if (!workspacePath) {
      throw new Error('No workspace selected');
    }
    const bridge = window.electronAPI?.office;
    if (!bridge?.pickAndImportMultiOfficeFiles) {
      throw new Error('useOfficeDocuments: unified import unavailable');
    }
    const result = await bridge.pickAndImportMultiOfficeFiles(workspacePath);
    if (!result) return null; // user cancelled
    const skipped: OfficeMultiImportSkipped[] = result.skipped.map((entry) => ({
      filename: entry.filename,
      reason: entry.reason,
      message: entry.message,
    }));
    return readStagedBatch(workspacePath, result.imported, skipped);
  }, [workspacePath, readStagedBatch]);

  const readDroppedMulti = useCallback(
    async (sourcePaths: string[]): Promise<OfficeMultiImportResult> => {
      if (!workspacePath) {
        throw new Error('No workspace selected');
      }
      const bridge = window.electronAPI?.office;
      if (!bridge?.importDroppedMultiOfficeFiles) {
        throw new Error('useOfficeDocuments: unified import unavailable');
      }
      const result = await bridge.importDroppedMultiOfficeFiles(workspacePath, sourcePaths);
      const skipped: OfficeMultiImportSkipped[] = result.skipped.map((entry) => ({
        filename: entry.filename,
        reason: entry.reason,
        message: entry.message,
      }));
      return readStagedBatch(workspacePath, result.imported, skipped);
    },
    [workspacePath, readStagedBatch],
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

  // Item 1.7: soft-delete lifecycle. Both actions re-fetch the current
  // view so the row moves between the live and archived lists immediately.
  const archiveDocument = useCallback(
    async (docId: string): Promise<void> => {
      await officeApi.archiveDocument(docId);
      await refresh();
    },
    [refresh],
  );

  const restoreDocument = useCallback(
    async (docId: string): Promise<void> => {
      await officeApi.restoreDocument(docId);
      await refresh();
    },
    [refresh],
  );

  // Round-3 N5: batch lifecycle. Sequential on purpose — the archive /
  // restore endpoints are cheap and the user sees a single summary when
  // the whole batch settled. Failures are collected per item (not
  // thrown) so the toolbar can report 成功 N 项 / 失败 M 项.
  const runBatch = useCallback(
    async (
      docIds: string[],
      op: (docId: string) => Promise<unknown>,
    ): Promise<OfficeBatchResult> => {
      const succeeded: string[] = [];
      const failed: string[] = [];
      for (const docId of docIds) {
        try {
          await op(docId);
          succeeded.push(docId);
        } catch {
          failed.push(docId);
        }
      }
      // One refetch for the whole batch — the per-doc actions refresh
      // after every call; doing that for N items would refetch N times.
      await refresh();
      return { succeeded, failed };
    },
    [refresh],
  );

  const batchArchive = useCallback(
    (docIds: string[]) => runBatch(docIds, (id) => officeApi.archiveDocument(id)),
    [runBatch],
  );

  const batchRestore = useCallback(
    (docIds: string[]) => runBatch(docIds, (id) => officeApi.restoreDocument(id)),
    [runBatch],
  );

  // Phase 1 Item A: archive every duplicate except the newest one. The
  // backend orders group members newest-first, so the first entry is the
  // one to keep. Reuses `runBatch` so the summary toast + single refetch
  // behavior match the other batch actions.
  const archiveAllButNewest = useCallback(
    (group: OfficeDuplicateGroup): Promise<OfficeBatchResult> => {
      const [, ...older] = group.documents;
      if (older.length === 0) {
        return Promise.resolve({ succeeded: [], failed: [] });
      }
      return runBatch(
        older.map((d) => d.id),
        (id) => officeApi.archiveDocument(id),
      );
    },
    [runBatch],
  );

  /**
   * Re-read a document's managed file (snapshot-restore follow-up).
   * The managed layout `<workspace>/office/<docType>/<docId>/<filename>`
   * mirrors electron/officePaths.buildManagedPath; the renderer keeps no
   * absolute path state, so it is rebuilt from the document record.
   */
  const readDocument = useCallback(
    async (docId: string): Promise<OfficeReadResult> => {
      const doc = documents.find((d) => d.id === docId);
      if (!doc || !workspacePath) {
        throw new Error('Document or workspace not found');
      }
      const managedPath = [
        workspacePath,
        'office',
        doc.doc_type,
        doc.id,
        doc.generated_filename,
      ].join('/');
      return readByType(doc.doc_type, managedPath);
    },
    [documents, workspacePath, readByType],
  );

  return {
    documents,
    loading,
    error,
    refresh,
    view,
    setView,
    q,
    setQ,
    docType,
    setDocType,
    sort,
    setSort,
    duplicateGroups,
    loadDuplicateGroups,
    archiveAllButNewest,
    importAndRead,
    importAndReadMulti,
    readDropped,
    readDroppedMulti,
    pendingDuplicate,
    resolvePendingDuplicate,
    saveAs,
    open,
    showInFolder,
    archiveDocument,
    restoreDocument,
    batchArchive,
    batchRestore,
    readDocument,
    findDocument,
  };
}

export function formatOfficeDocumentsBatchSummary(result: {
  succeeded: string[];
  failed: string[];
}): string {
  return `succeeded=${result.succeeded.length} · failed=${result.failed.length}`;
}

export function formatOfficeDocumentsBatchJson(result: {
  succeeded: string[];
  failed: string[];
}): string {
  return JSON.stringify(
    {
      total: result.succeeded.length + result.failed.length,
      succeededCount: result.succeeded.length,
      failedCount: result.failed.length,
      succeeded: result.succeeded,
      failed: result.failed,
    },
    null,
    2,
  );
}

export function auditUseOfficeDocumentsGovernance(): {
  moduleId: string;
  phase: string;
  status: 'ready';
} {
  return {
    moduleId: 'src/features/office/useOfficeDocuments.ts',
    phase: 'P165',
    status: 'ready',
  };
}
