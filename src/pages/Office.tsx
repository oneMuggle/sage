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
 * Reads: per-user Q3 includes "MVP 包含编辑现有", but editing endpoints
 * are deferred to Phase 2 per plan §4.1.4 step 17. This page only
 * implements read + list + delete for Phase 1.3.
 */

import { FileSpreadsheet, FileText, FolderOpen, Presentation } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import {
  OfficeDocumentList,
  OfficeFilePicker,
  OfficePreviewPanel,
  useOfficeDocuments,
  type OfficePreviewData,
} from '../features/office';
import type { OfficeDocType } from '../shared/api/types';

export function Office() {
  const [workspacePath, setWorkspacePath] = useState<string | null>(null);
  const [preview, setPreview] = useState<OfficePreviewData | null>(null);
  const [previewingPath, setPreviewingPath] = useState<string | null>(null);

  const { documents, loading, error, refresh, readPpt, readWord, readExcel, deleteDocument } =
    useOfficeDocuments(workspacePath);

  const handleSelectWorkspace = async () => {
    const dir = await window.electronAPI?.selectDirectory({ intent: 'open' });
    if (dir) {
      setWorkspacePath(dir);
      setPreview(null);
      setPreviewingPath(null);
    }
  };

  const handlePickAndRead = (docType: OfficeDocType) => async (filePath: string) => {
    if (!workspacePath) {
      toast.error('请先选择工作区目录');
      return;
    }
    setPreviewingPath(filePath);
    try {
      let data: OfficePreviewData;
      if (docType === 'ppt') {
        data = { docType: 'ppt', data: await readPpt(filePath) };
      } else if (docType === 'word') {
        data = { docType: 'word', data: await readWord(filePath) };
      } else {
        data = { docType: 'excel', data: await readExcel(filePath) };
      }
      setPreview(data);
      // Refresh list to reflect new parsed record (if backend saved one)
      await refresh();
      toast.success('文档读取成功');
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`读取失败: ${msg}`);
      setPreview(null);
    } finally {
      setPreviewingPath(null);
    }
  };

  const handleDelete = async (docId: string) => {
    try {
      await deleteDocument(docId);
      toast.success('已删除');
      setPreview(null);
      setPreviewingPath(null);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`删除失败: ${msg}`);
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
            {/* Left: 3 file pickers */}
            <div className="space-y-3">
              <h2 className="text-sm font-medium text-text-secondary">选择文件</h2>
              <OfficeFilePicker
                docType="ppt"
                onFileSelected={handlePickAndRead('ppt')}
                disabled={!!previewingPath}
              >
                <span className="flex items-center gap-1.5">
                  <Presentation className="w-3.5 h-3.5" /> 选择 PowerPoint
                </span>
              </OfficeFilePicker>
              <OfficeFilePicker
                docType="word"
                onFileSelected={handlePickAndRead('word')}
                disabled={!!previewingPath}
              >
                <span className="flex items-center gap-1.5">
                  <FileText className="w-3.5 h-3.5" /> 选择 Word
                </span>
              </OfficeFilePicker>
              <OfficeFilePicker
                docType="excel"
                onFileSelected={handlePickAndRead('excel')}
                disabled={!!previewingPath}
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
            <OfficeDocumentList documents={documents} loading={loading} onDelete={handleDelete} />
          </div>
        </>
      )}
    </div>
  );
}

export default Office;
