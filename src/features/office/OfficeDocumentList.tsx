/**
 * OfficeDocumentList — workspace history (Phase 1.3, plan §4.1.4 step 16).
 *
 * Lists previously read/generated office documents in the current workspace.
 *
 * M0 Task 6 (2026-07-23): rewired actions to the M0 management set:
 *   - Save As (native dialog → copy managed file to chosen path)
 *   - Open (shell.openPath on the managed file)
 *   - Show in Folder (shell.showItemInFolder)
 * The Phase 1.3 delete action was REMOVED. The brief is explicit: do
 * not expose a permanent delete action from the M0 management view;
 * archive/restore and the user confirmation flow are implemented in
 * M3–M5. Existing DB delete code may remain unreachable until the
 * archive migration is complete.
 */

import { FolderOpen, FileSpreadsheet, FileText, Presentation, Save } from 'lucide-react';

import type { OfficeDocType, OfficeDocumentSummary } from '../../shared/api/types';

const DOC_TYPE_ICONS: Record<OfficeDocType, React.ReactNode> = {
  ppt: <Presentation className="w-4 h-4" />,
  word: <FileText className="w-4 h-4" />,
  excel: <FileSpreadsheet className="w-4 h-4" />,
};

const DOC_TYPE_LABELS: Record<OfficeDocType, string> = {
  ppt: 'PPT',
  word: 'Word',
  excel: 'Excel',
};

const STATUS_LABELS: Record<OfficeDocumentSummary['status'], string> = {
  parsed: '已读取',
  generated: '已生成',
  edited: '已编辑',
};

export interface OfficeDocumentListProps {
  documents: OfficeDocumentSummary[];
  loading: boolean;
  /** Native Save As dialog → copy managed file to chosen path. */
  onSaveAs?: (docId: string) => void | Promise<void>;
  /** shell.openPath on the managed file. */
  onOpen?: (docId: string) => void | Promise<void>;
  /** shell.showItemInFolder on the managed file. */
  onShowInFolder?: (docId: string) => void | Promise<void>;
}

export function OfficeDocumentList({
  documents,
  loading,
  onSaveAs,
  onOpen,
  onShowInFolder,
}: OfficeDocumentListProps) {
  if (loading) {
    return <div className="text-sm text-muted p-4 text-center">加载中...</div>;
  }
  if (documents.length === 0) {
    return (
      <div className="text-sm text-muted p-4 text-center border border-dashed border-border rounded-lg">
        暂无历史文档
      </div>
    );
  }
  return (
    <ul className="space-y-2" data-testid="office-document-list">
      {documents.map((doc) => (
        <li
          key={doc.id}
          className="flex items-center gap-3 p-3 border border-border rounded-lg bg-surface"
        >
          <div className="text-muted">{DOC_TYPE_ICONS[doc.doc_type]}</div>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium text-text truncate">
              {doc.original_filename ?? doc.generated_filename}
            </div>
            <div className="text-xs text-muted flex items-center gap-2">
              <span>{DOC_TYPE_LABELS[doc.doc_type]}</span>
              <span>·</span>
              <span>{STATUS_LABELS[doc.status]}</span>
              <span>·</span>
              <span>{(doc.metadata.file_size_bytes / 1024).toFixed(1)} KB</span>
              <span>·</span>
              <span>{new Date(doc.created_at).toLocaleString()}</span>
            </div>
          </div>
          <div className="flex items-center gap-1">
            {onSaveAs && (
              <button
                type="button"
                onClick={() => void onSaveAs(doc.id)}
                className="p-1.5 rounded text-muted hover:text-primary hover:bg-primary/10 transition-colors"
                aria-label="Save As"
              >
                <Save className="w-4 h-4" />
              </button>
            )}
            {onOpen && (
              <button
                type="button"
                onClick={() => void onOpen(doc.id)}
                className="p-1.5 rounded text-muted hover:text-primary hover:bg-primary/10 transition-colors"
                aria-label="Open"
              >
                <FileText className="w-4 h-4" />
              </button>
            )}
            {onShowInFolder && (
              <button
                type="button"
                onClick={() => void onShowInFolder(doc.id)}
                className="p-1.5 rounded text-muted hover:text-primary hover:bg-primary/10 transition-colors"
                aria-label="Show in Folder"
              >
                <FolderOpen className="w-4 h-4" />
              </button>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}
