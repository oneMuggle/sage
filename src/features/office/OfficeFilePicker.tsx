/**
 * OfficeFilePicker — file selection UI for /office page (Phase 1.3, plan §4.1.4 step 16).
 *
 * Per user Q2: supports native file dialog + HTML5 drag-and-drop.
 *
 * M0 Task 6 (2026-07-23): wired to the Electron managed gateway (M0 Task 5).
 * M0 Task 6 fix (2026-07-24): the picker is now the *single* interaction
 * entry for a read. It no longer imports files itself — it delegates the
 * whole pick → import → read → complete/discard lifecycle to the hook:
 *   - click  → `onPick()`            (hook's `importAndRead(docType)`)
 *   - drop   → `onDropFile(source)`  (hook's `readDropped(docType, source)`)
 * Keeping a single owner of the import token (the hook) avoids the earlier
 * double-import / dead-drop bug where the page rendered the picker
 * `disabled` and drove reads from a sibling "导入并读取" button.
 *
 * Legacy `.doc` / `.xls` / `.ppt` files are rejected at the drag-and-drop
 * boundary — the Electron dialog filters already block them at the
 * native-pick path, but dropped files can carry any extension.
 *
 * Usage:
 * ```tsx
 * <OfficeFilePicker
 *   docType="ppt"
 *   workspacePath={workspacePath}
 *   onPick={handleImportAndRead('ppt')}
 *   onDropFile={handleReadDropped('ppt')}
 * >
 *   Click to pick a .pptx
 * </OfficeFilePicker>
 * ```
 */

import { FileText, Upload } from 'lucide-react';
import { useState, type ReactNode } from 'react';

import type { OfficeDocType } from '../../shared/api/types';

export interface OfficeFilePickerProps {
  docType: OfficeDocType;
  workspacePath: string | null;
  /**
   * Click path: open the native dialog, then import + read via the hook.
   * The picker does not know about the managed path or import token — the
   * hook owns that lifecycle.
   */
  onPick: () => void | Promise<void>;
  /**
   * Drop path: the picker resolves the dropped file's OS source path and
   * hands it to the caller, which imports + reads it via the hook.
   */
  onDropFile: (sourcePath: string) => void | Promise<void>;
  children?: ReactNode;
  disabled?: boolean;
}

const DOC_TYPE_LABELS: Record<OfficeDocType, string> = {
  ppt: 'PowerPoint (.pptx)',
  word: 'Word (.docx)',
  excel: 'Excel (.xlsx)',
};

const DOC_TYPE_MODERN_EXT: Record<OfficeDocType, string> = {
  ppt: 'pptx',
  word: 'docx',
  excel: 'xlsx',
};

/**
 * Returns true iff the file's extension is the modern OOXML type
 * expected for `docType`. We never accept legacy `.doc` / `.xls` / `.ppt`
 * — Sage cannot parse them and silently rejecting at the UI boundary
 * keeps the failure-mode consistent with the native dialog.
 */
function hasModernExtension(fileName: string, docType: OfficeDocType): boolean {
  const lowered = fileName.toLowerCase();
  return lowered.endsWith(`.${DOC_TYPE_MODERN_EXT[docType]}`);
}

export function OfficeFilePicker({
  docType,
  workspacePath,
  onPick,
  onDropFile,
  children,
  disabled,
}: OfficeFilePickerProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleClick = async () => {
    if (disabled || busy) return;
    if (!workspacePath) {
      setError('请先选择工作区');
      return;
    }
    setError(null);
    setBusy(true);
    try {
      // The hook (onPick → importAndRead) owns the dialog + import + read +
      // complete/discard flow and surfaces its own errors (page toast).
      await onPick();
    } finally {
      setBusy(false);
    }
  };

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    if (!isDragging) setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDrop = async (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    if (disabled || busy) return;
    if (!workspacePath) {
      setError('请先选择工作区');
      return;
    }
    const file = e.dataTransfer.files[0];
    if (!file) return;
    if (!hasModernExtension(file.name, docType)) {
      setError(`不支持的格式: ${file.name}（仅接受 .${DOC_TYPE_MODERN_EXT[docType]}）`);
      return;
    }
    // Dropped files have File.path on Electron; null on web
    const filePath = (file as File & { path?: string }).path;
    if (!filePath) {
      setError('无法获取文件路径（Web 环境下不支持拖拽）');
      return;
    }
    setError(null);
    setBusy(true);
    try {
      await onDropFile(filePath);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      onClick={handleClick}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className={[
        'flex flex-col items-center justify-center gap-2',
        'p-6 border-2 border-dashed rounded-lg cursor-pointer',
        'transition-colors',
        isDragging
          ? 'border-primary bg-primary/10'
          : 'border-border bg-bg-subtle hover:border-primary/50',
        disabled || busy ? 'opacity-50 cursor-not-allowed' : '',
      ].join(' ')}
      data-testid={`office-file-picker-${docType}`}
    >
      {busy ? (
        <Upload className="w-8 h-8 animate-pulse text-muted" />
      ) : (
        <FileText className="w-8 h-8 text-muted" />
      )}
      <div className="text-sm font-medium text-text">
        {children ?? `选择 ${DOC_TYPE_LABELS[docType]}`}
      </div>
      <div className="text-xs text-muted">或拖拽 .{DOC_TYPE_MODERN_EXT[docType]} 文件到此</div>
      {error && (
        <div className="text-xs text-error" data-testid="office-file-picker-error">
          {error}
        </div>
      )}
    </div>
  );
}
