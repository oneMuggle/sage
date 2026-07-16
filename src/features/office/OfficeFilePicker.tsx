/**
 * OfficeFilePicker — file selection UI for /office page (Phase 1.3, plan §4.1.4 step 16).
 *
 * Per user Q2: supports native file dialog + HTML5 drag-and-drop.
 *
 * Usage:
 * ```tsx
 * <OfficeFilePicker docType="ppt" onFileSelected={async (path) => await readPpt(path)}>
 *   Click to pick a .pptx
 * </OfficeFilePicker>
 * ```
 */

import { useState, type ReactNode } from 'react';
import { FileText, Upload } from 'lucide-react';

import type { OfficeDocType } from '../../shared/api/types';

export interface OfficeFilePickerProps {
  docType: OfficeDocType;
  onFileSelected: (filePath: string) => void | Promise<void>;
  children?: ReactNode;
  disabled?: boolean;
}

const DOC_TYPE_LABELS: Record<OfficeDocType, string> = {
  ppt: 'PowerPoint (.pptx)',
  word: 'Word (.docx)',
  excel: 'Excel (.xlsx)',
};

export function OfficeFilePicker({
  docType,
  onFileSelected,
  children,
  disabled,
}: OfficeFilePickerProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [busy, setBusy] = useState(false);

  const handleClick = async () => {
    if (disabled || busy) return;
    setBusy(true);
    try {
      const picked = await window.electronAPI?.office.pickOfficeFile(docType);
      if (picked) {
        await onFileSelected(picked.path);
      }
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
    const file = e.dataTransfer.files[0];
    if (!file) return;
    // Dropped files have File.path on Electron; null on web
    const filePath = (file as File & { path?: string }).path;
    if (!filePath) {
      console.warn('Dropped file has no path (web environment?)');
      return;
    }
    setBusy(true);
    try {
      await onFileSelected(filePath);
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
      <div className="text-xs text-muted">或拖拽文件到此</div>
    </div>
  );
}