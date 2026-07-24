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
 */

import { FileSpreadsheet, FileText, FolderOpen, Presentation } from 'lucide-react';
import { useRef, useState } from 'react';
import { toast } from 'sonner';

import {
  OfficeDocumentList,
  OfficeFilePicker,
  OfficeGenerateForm,
  OfficePreviewPanel,
  useOfficeDocuments,
  type OfficePreviewData,
  type OfficeReadResult,
} from '../features/office';
import type { OfficeDocType } from '../shared/api/types';

export function Office() {
  const [workspacePath, setWorkspacePath] = useState<string | null>(null);
  const [preview, setPreview] = useState<OfficePreviewData | null>(null);
  // HIGH FIX: stale-read guard. Increments on every handleImportAndRead
  // invocation; setPreview checks the captured id before applying state.
  // Without this, a read that resolves after a workspace change
  // (or a faster subsequent read) would overwrite the correct preview
  // with stale data from the wrong workspace.
  const readIdRef = useRef(0);

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

  const handleSelectWorkspace = async () => {
    try {
      const api = window.electronAPI;
      if (!api) {
        // No preload bridge → running outside Electron (e.g. plain browser).
        // Tell the user instead of silently no-op'ing.
        toast.error('IPC 桥接不可用,请在 Electron 桌面端运行');
        return;
      }
      const dir = await api.selectDirectory({ intent: 'open' });
      if (dir) {
        // Bump readIdRef so any in-flight read from the previous workspace
        // is correctly discarded by the stale-read guard.
        readIdRef.current += 1;
        setWorkspacePath(dir);
        setPreview(null);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`选择工作区失败: ${msg}`);
    }
  };

  const toPreview = (docType: OfficeDocType, data: OfficeReadResult): OfficePreviewData => ({
    docType,
    // The discriminated union types line up by docType; this is safe
    // because we are passing the same `data` we just read.
    data: data as never,
  });

  const handleImportAndRead = (docType: OfficeDocType) => async () => {
    if (!workspacePath) {
      toast.error('请先选择工作区目录');
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
      toast.success('文档读取成功');
    } catch (e) {
      // If this read is stale, suppress its error toast (a newer read
      // is in flight and the user will see ITS result instead)
      if (myReadId !== readIdRef.current) return;
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`读取失败: ${msg}`);
      setPreview(null);
    }
  };

  // Drop path: the picker already resolved the OS source path; the hook
  // imports it into the managed area and reads it (same complete/discard
  // lifecycle as importAndRead). Shares the stale-read guard so a workspace
  // switch mid-read still discards stale data.
  const handleReadDropped = (docType: OfficeDocType) => async (sourcePath: string) => {
    if (!workspacePath) {
      toast.error('请先选择工作区目录');
      return;
    }
    const myReadId = ++readIdRef.current;
    try {
      const data = await readDropped(docType, sourcePath);
      if (myReadId !== readIdRef.current) return;
      setPreview(toPreview(docType, data));
      await refresh();
      if (myReadId !== readIdRef.current) return;
      toast.success('文档读取成功');
    } catch (e) {
      if (myReadId !== readIdRef.current) return;
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`读取失败: ${msg}`);
      setPreview(null);
    }
  };

  const handleSaveAs = async (docId: string) => {
    try {
      const savedPath = await saveAs(docId);
      if (savedPath) {
        toast.success(`已另存为 ${savedPath}`);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`另存为失败: ${msg}`);
    }
  };

  const handleOpen = async (docId: string) => {
    try {
      await open(docId);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`打开失败: ${msg}`);
    }
  };

  const handleShowInFolder = async (docId: string) => {
    try {
      await showInFolder(docId);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`显示文件夹失败: ${msg}`);
    }
  };

  return (
    <div className="flex-1 flex flex-col gap-4 p-6 overflow-y-auto" data-testid="office-page">
      {/* Header */}
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-semibold text-text">Office 文档</h1>
        <div className="ml-auto flex items-center gap-2 text-sm text-muted">
          <FolderOpen className="w-4 h-4" />
          {workspacePath ? (
            <button
              onClick={handleSelectWorkspace}
              className="text-primary hover:underline"
              data-testid="office-workspace-path"
            >
              {workspacePath}
            </button>
          ) : (
            <button
              onClick={handleSelectWorkspace}
              className="px-3 py-1.5 rounded bg-primary text-text-inverse text-sm hover:bg-primary-hover"
            >
              选择工作区
            </button>
          )}
        </div>
      </div>

      {!workspacePath ? (
        <div className="flex items-center justify-center p-12 text-muted text-sm border border-dashed border-border rounded-lg">
          请先选择工作区目录以开始使用
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
              <h2 className="text-sm font-medium text-text-secondary">选择文件</h2>
              <OfficeFilePicker
                docType="ppt"
                workspacePath={workspacePath}
                onPick={handleImportAndRead('ppt')}
                onDropFile={handleReadDropped('ppt')}
                disabled={loading}
              >
                <span className="flex items-center gap-1.5">
                  <Presentation className="w-3.5 h-3.5" /> 选择 PowerPoint
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
                  <FileText className="w-3.5 h-3.5" /> 选择 Word
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
                  <FileSpreadsheet className="w-3.5 h-3.5" /> 选择 Excel
                </span>
              </OfficeFilePicker>
            </div>

            {/* Right: preview panel */}
            <div>
              <h2 className="text-sm font-medium text-text-secondary mb-3">预览</h2>
              <OfficePreviewPanel preview={preview} />
            </div>
          </div>

          {/* Document list */}
          <div>
            <h2 className="text-sm font-medium text-text-secondary mb-3">
              历史记录 ({documents.length})
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
    </div>
  );
}

export default Office;
