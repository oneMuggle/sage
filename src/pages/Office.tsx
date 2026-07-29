/**
 * /office page (Phase 1.3, plan §4.1.4 step 17).
 *
 * Layout:
 *   ┌──────────────────────────────────────┐
 *   │ Header (workspace selector)            │
 *   ├──────────┬───────────────────────────┤
 *   │ 3 file   │   Preview panel (right)   │
 *   │ pickers  │   (PPT slides / Word text │
 *   │ (PPTX/   │   / Excel sheets)        │
 *   │ DOCX/    │                          │
 *   │ XLSX)    │                          │
 *   ├──────────┴───────────────────────────┤
 *   │ Document list (history)              │
 *   └──────────────────────────────────────┘
 *
 * M0 Task 6 (2026-07-23): rewired the file-pick flow through the
 * Electron managed-file gateway. The picker now goes through
 * `importAndRead` which atomic-copies the file into the managed area
 * and returns a `managedPath` — the page no longer sees the original
 * source path at any point. The M0 management set replaces the
 * Phase 1.3 delete action with Save As / Open / Show in Folder; the
 * destructive delete flow lives in M3–M5.
 *
 * Task 5 (2026-07-26): removed the page-local `workspacePath` useState.
 * The page now reads `useCurrentWorkspace()` from the SessionWorkspace
 * provider (mounted in AppProviders) — the same source Chat.tsx uses,
 * so workspace state is unified across the app. Bind / change / revoke
 * go through <WorkspaceBindModal>; the provider owns the bind/revoke
 * IPC. The stale-read guard (`readIdRef`) is preserved: when the user
 * switches workspaces, any in-flight read is dropped before its data
 * reaches `setPreview`.
 */

import { FileSpreadsheet, FileText, FolderOpen, Presentation } from 'lucide-react';
import { useRef, useState } from 'react';
import { toast } from 'sonner';

import { useWorkspaceContext } from '../app/providers/SessionWorkspaceProvider';
import {
  OfficeDocumentList,
  OfficeFilePicker,
  OfficeGenerateForm,
  OfficePreviewPanel,
  useOfficeDocuments,
  type OfficePreviewData,
  type OfficeReadResult,
} from '../features/office';
import { WorkspaceBindModal } from '../features/workspace';
import type { OfficeDocType } from '../shared/api/types';
import { useI18n } from '../shared/lib/i18n';
import { useCurrentWorkspace } from '../shared/lib/workspaceContext';

export function Office() {
  // Task 5: workspacePath now comes from SessionWorkspaceProvider, not
  // local state. AppProviders mounts the provider; Chat.tsx reads from
  // the same context. `?? null` keeps the local consumer contract
  // (which expects `string | null`) unchanged.
  const { t } = useI18n();
  const workspacePath = useCurrentWorkspace() ?? null;
  const { bind, revoke, status: workspaceStatus, error: workspaceError } =
    useWorkspaceContext();

  const [preview, setPreview] = useState<OfficePreviewData | null>(null);
  // HIGH FIX: stale-read guard. Increments on every handleImportAndRead
  // invocation; setPreview checks the captured id before applying state.
  // Without this, a read that resolves after a workspace change
  // (or a faster subsequent read) would overwrite the correct preview
  // with stale data from the wrong workspace.
  const readIdRef = useRef(0);

  // Workspace bind modal is opened by the header button (initial bind)
  // or the workspace-path chip (change).
  const [isBindModalOpen, setIsBindModalOpen] = useState(false);

  const {
    documents,
    loading,
    error,
    refresh,
    importAndRead,
    readDropped,
    saveAs,
    open,
    showInFolder,
  } = useOfficeDocuments(workspacePath);

  // The bind modal owns its own IPC; we just need to know when the
  // workspace has actually changed so the stale-read guard can drop any
  // in-flight read from the previous workspace.
  const handleBindModalClose = () => {
    setIsBindModalOpen(false);
    // Workspace changed (or user cancelled) — bump readIdRef so any
    // in-flight read is correctly discarded.
    readIdRef.current += 1;
    setPreview(null);
  };

  const toPreview = (docType: OfficeDocType, data: OfficeReadResult): OfficePreviewData => ({
    docType,
    // The discriminated union types line up by docType; this is safe
    // because we are passing the same `data` we just read.
    data: data as never,
  });

  const handleImportAndRead = (docType: OfficeDocType) => async () => {
    if (!workspacePath) {
      toast.error(t('office.toast.selectWorkspace'));
      return;
    }
    const myReadId = ++readIdRef.current;
    try {
      const data = await importAndRead(docType);
      if (data === null) return; // user cancelled
      // Stale-read guard: only commit preview if this is still the latest
      if (myReadId !== readIdRef.current) return;
      setPreview(toPreview(docType, data));
      await refresh();
      // Re-check after the await (refresh may take time; another read
      // could have started in the meantime)
      if (myReadId !== readIdRef.current) return;
      toast.success(t('office.toast.readSuccess'));
    } catch (e) {
      // If this read is stale, suppress its error toast (a newer read
      // is in flight and the user will see ITS result instead)
      if (myReadId !== readIdRef.current) return;
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`${t('office.toast.readFailed')}: ${msg}`);
      setPreview(null);
    }
  };

  // Drop path: the picker already resolved the OS source path; the hook
  // imports it into the managed area and reads it (same complete/discard
  // lifecycle as importAndRead). Shares the stale-read guard so a workspace
  // switch mid-read still discards stale data.
  const handleReadDropped = (docType: OfficeDocType) => async (sourcePath: string) => {
    if (!workspacePath) {
      toast.error(t('office.toast.selectWorkspace'));
      return;
    }
    const myReadId = ++readIdRef.current;
    try {
      const data = await readDropped(docType, sourcePath);
      if (myReadId !== readIdRef.current) return;
      setPreview(toPreview(docType, data));
      await refresh();
      if (myReadId !== readIdRef.current) return;
      toast.success(t('office.toast.readSuccess'));
    } catch (e) {
      if (myReadId !== readIdRef.current) return;
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`${t('office.toast.readFailed')}: ${msg}`);
      setPreview(null);
    }
  };

  const handleSaveAs = async (docId: string) => {
    try {
      const savedPath = await saveAs(docId);
      if (savedPath) {
        toast.success(`${t('office.toast.savedAs')} ${savedPath}`);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`${t('office.toast.saveAsFailed')}: ${msg}`);
    }
  };

  const handleOpen = async (docId: string) => {
    try {
      await open(docId);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`${t('office.toast.openFailed')}: ${msg}`);
    }
  };

  const handleShowInFolder = async (docId: string) => {
    try {
      await showInFolder(docId);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`${t('office.toast.showInFolderFailed')}: ${msg}`);
    }
  };

  return (
    <div className="flex-1 flex flex-col gap-4 p-6 overflow-y-auto" data-testid="office-page">
      {/* Header */}
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-semibold text-text">{t('office.title')}</h1>
        <div className="ml-auto flex items-center gap-2 text-sm text-muted">
          <FolderOpen className="w-4 h-4" />
          {workspacePath ? (
            <button
              onClick={() => setIsBindModalOpen(true)}
              className="text-primary hover:underline"
              data-testid="office-workspace-path"
            >
              {workspacePath}
            </button>
          ) : (
            <button
              onClick={() => setIsBindModalOpen(true)}
              className="px-3 py-1.5 rounded bg-primary text-text-inverse text-sm hover:bg-primary-hover"
              data-testid="office-workspace-pick"
            >
              {t('office.selectWorkspace')}
            </button>
          )}
        </div>
      </div>

      {/* workspaceStatus === 'error' (initial load failed) — surface
          it here so users see it on the Office page even when the rest
          of the page is healthy. The modal also surfaces errors during
          bind/revoke. Shown above both branches so a fresh-error user
          (no binding yet) still sees the cause. */}
      {workspaceStatus === 'error' && workspaceError && (
        <div
          data-testid="office-workspace-error"
          className="px-4 py-3 bg-error/10 border border-error/30 rounded text-sm text-error"
        >
          {workspaceError}
        </div>
      )}

      {!workspacePath ? (
        <div className="flex items-center justify-center p-12 text-muted text-sm border border-dashed border-border rounded-lg">
          {t('office.emptyState')}
        </div>
      ) : (
        <>
          {error && (
            <div className="px-4 py-3 bg-error/10 border border-error/30 rounded text-sm text-error">
              {error}
            </div>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Left: 3 file pickers — click opens the dialog, drop imports
                the dropped file. Both paths go through the hook's managed
                import + read lifecycle. */}
            <div className="space-y-3">
              <h2 className="text-sm font-medium text-text-secondary">
                {t('office.section.pickFile')}
              </h2>
              <OfficeFilePicker
                docType="ppt"
                workspacePath={workspacePath}
                onPick={handleImportAndRead('ppt')}
                onDropFile={handleReadDropped('ppt')}
                disabled={loading}
              >
                <span className="flex items-center gap-1.5">
                  <Presentation className="w-3.5 h-3.5" /> {t('office.pick.ppt')}
                </span>
              </OfficeFilePicker>
              <OfficeFilePicker
                docType="word"
                workspacePath={workspacePath}
                onPick={handleImportAndRead('word')}
                onDropFile={handleReadDropped('word')}
                disabled={loading}
              >
                <span className="flex items-center gap-1.5">
                  <FileText className="w-3.5 h-3.5" /> {t('office.pick.word')}
                </span>
              </OfficeFilePicker>
              <OfficeFilePicker
                docType="excel"
                workspacePath={workspacePath}
                onPick={handleImportAndRead('excel')}
                onDropFile={handleReadDropped('excel')}
                disabled={loading}
              >
                <span className="flex items-center gap-1.5">
                  <FileSpreadsheet className="w-3.5 h-3.5" /> {t('office.pick.excel')}
                </span>
              </OfficeFilePicker>
            </div>

            {/* Right: preview panel */}
            <div>
              <h2 className="text-sm font-medium text-text-secondary mb-3">
                {t('office.section.preview')}
              </h2>
              <OfficePreviewPanel preview={preview} />
            </div>
          </div>

          {/* Document list */}
          <div>
            <h2 className="text-sm font-medium text-text-secondary mb-3">
              {t('office.section.history')} ({documents.length})
            </h2>
            <OfficeDocumentList
              documents={documents}
              loading={loading}
              onSaveAs={handleSaveAs}
              onOpen={handleOpen}
              onShowInFolder={handleShowInFolder}
            />
          </div>

          {/* Generate form (Phase 1.4) */}
          <OfficeGenerateForm workspacePath={workspacePath} onGenerated={refresh} />
        </>
      )}

      {/* Bind / change / revoke modal. Mounted once; opens via the
          header button or the workspace-path chip. The provider owns
          the IPC; the modal just translates clicks. */}
      <WorkspaceBindModal
        isOpen={isBindModalOpen}
        onClose={handleBindModalClose}
        currentPath={workspacePath}
        bind={bind}
        revoke={revoke}
      />
    </div>
  );
}

export default Office;