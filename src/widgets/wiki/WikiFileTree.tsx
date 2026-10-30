// Wiki File Tree - recursive tree view of wiki files
import {
  ChevronRight,
  ChevronDown,
  Copy,
  FileText,
  Folder,
  Pencil,
  Plus,
  Trash2,
} from 'lucide-react';
import { useRef, useState } from 'react';
import { toast } from 'sonner';

import { useWikiStore } from '../../entities/wiki/store';
import { copyToClipboard } from '../../shared/lib/clipboard';
import { fillTemplate } from '../../shared/lib/formatTemplate';
import { useI18n } from '../../shared/lib/i18n';
import type { FileNode } from '../../shared/types/wiki';
import { confirmDialog } from '../../shared/ui/ConfirmDialog/confirmService';
import { ContextMenu } from '../../shared/ui/ContextMenu/ContextMenu';
import type { ContextMenuItemSpec } from '../../shared/ui/ContextMenu/types';

export function WikiFileTree() {
  const fileTree = useWikiStore((s) => s.fileTree);
  const selectedFile = useWikiStore((s) => s.selectedFile);
  const openFile = useWikiStore((s) => s.openFile);
  const loadFileTree = useWikiStore((s) => s.loadFileTree);

  useState(() => {
    loadFileTree();
  });

  if (fileTree.length === 0) {
    return <div className="p-4 text-center text-sm text-muted">暂无文件</div>;
  }

  return (
    <div className="py-2">
      {fileTree.map((node) => (
        <TreeNode
          key={node.path}
          node={node}
          depth={0}
          selectedFile={selectedFile}
          onFileClick={(path) => openFile(path)}
        />
      ))}
    </div>
  );
}

type EditMode = 'idle' | 'rename' | 'create';

function TreeNode({
  node,
  depth,
  selectedFile,
  onFileClick,
}: {
  node: FileNode;
  depth: number;
  selectedFile: string | null;
  onFileClick: (path: string) => void;
}) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(depth === 0);
  const [mode, setMode] = useState<EditMode>('idle');
  const [draft, setDraft] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const submittingRef = useRef(false);
  const cancelledRef = useRef(false);
  const createFile = useWikiStore((s) => s.createFile);
  const renameFile = useWikiStore((s) => s.renameFile);
  const deleteFile = useWikiStore((s) => s.deleteFile);
  const openFile = useWikiStore((s) => s.openFile);
  const isSelected = selectedFile === node.path;

  const handleClick = () => {
    if (node.is_dir) {
      setExpanded(!expanded);
    } else {
      onFileClick(node.path);
    }
  };

  const beginEdit = (next: Exclude<EditMode, 'idle'>) => {
    cancelledRef.current = false;
    setDraft(next === 'rename' ? node.name : '');
    setMode(next);
    if (next === 'create') setExpanded(true);
    requestAnimationFrame(() => {
      inputRef.current?.focus();
      inputRef.current?.select();
    });
  };

  const cancelEdit = () => {
    cancelledRef.current = true;
    setMode('idle');
  };

  const submitEdit = async () => {
    if (mode === 'idle' || submittingRef.current) return;
    if (cancelledRef.current) {
      cancelledRef.current = false;
      return;
    }
    submittingRef.current = true;
    const currentMode = mode;
    const value = draft.trim();
    setMode('idle');
    try {
      if (!value) {
        toast.error(t('contextMenu.wiki.nameRequired'));
        return;
      }
      if (value.includes('/') || value.includes('..')) {
        toast.error(t('contextMenu.wiki.nameInvalid'));
        return;
      }
      const fileName = /\.\w+$/.test(value) ? value : `${value}.md`;
      if (currentMode === 'rename') {
        if (fileName === node.name) return;
        await renameFile(node.path, fileName);
      } else {
        await createFile(node.path, fileName);
      }
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      toast.error(
        fillTemplate(
          t(
            currentMode === 'rename'
              ? 'contextMenu.wiki.renameFailed'
              : 'contextMenu.wiki.createFailed',
          ),
          { message },
        ),
      );
    } finally {
      submittingRef.current = false;
    }
  };

  const confirmDelete = async () => {
    const confirmed = await confirmDialog({
      title: t('contextMenu.wiki.deleteTitle'),
      message: fillTemplate(t('contextMenu.wiki.deleteMessage'), { path: node.path }),
      confirmLabel: t('common.delete'),
      danger: true,
    });
    if (!confirmed) return;
    try {
      await deleteFile(node.path);
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      toast.error(fillTemplate(t('contextMenu.wiki.deleteFailed'), { message }));
    }
  };

  const copy = (text: string) =>
    void copyToClipboard(text, {
      successMessage: t('contextMenu.common.copied'),
      errorMessage: t('contextMenu.common.copyFailed'),
    });

  const menuItems = (): ContextMenuItemSpec[] => {
    const items: ContextMenuItemSpec[] = [];
    if (node.is_dir) {
      items.push({
        id: 'wiki-new-file',
        label: t('contextMenu.wiki.newFile'),
        icon: Plus,
        onSelect: () => beginEdit('create'),
      });
    } else {
      items.push(
        {
          id: 'wiki-open',
          label: t('contextMenu.common.open'),
          icon: FileText,
          onSelect: () => openFile(node.path),
        },
        {
          id: 'wiki-rename',
          label: t('contextMenu.common.rename'),
          icon: Pencil,
          onSelect: () => beginEdit('rename'),
        },
      );
    }
    items.push(
      { id: 'wiki-sep-copy', kind: 'separator' },
      {
        id: 'wiki-copy-path',
        label: t('contextMenu.common.copyPath'),
        icon: Copy,
        onSelect: () => copy(node.path),
      },
      {
        id: 'wiki-copy-name',
        label: t('contextMenu.common.copyName'),
        icon: Copy,
        onSelect: () => copy(node.name),
      },
      { id: 'wiki-sep-delete', kind: 'separator' },
      {
        id: 'wiki-delete',
        label: t('contextMenu.common.delete'),
        icon: Trash2,
        destructive: true,
        onSelect: confirmDelete,
      },
    );
    return items;
  };

  const paddingLeft = depth * 12 + 8;

  return (
    <div>
      <ContextMenu items={menuItems} enabled={mode === 'idle'}>
        <button
          onClick={handleClick}
          data-testid={node.is_dir ? 'wiki-dir-node' : 'wiki-file-node'}
          data-path={node.path}
          className={`flex w-full items-center gap-1.5 py-1 pr-2 text-left text-sm hover:bg-bg-muted transition-colors ${
            isSelected ? 'bg-primary/10 text-primary' : 'text-text-secondary'
          }`}
          style={{ paddingLeft: `${paddingLeft}px` }}
        >
          {node.is_dir ? (
            <>
              {expanded ? (
                <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted" />
              ) : (
                <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted" />
              )}
              <Folder className="h-3.5 w-3.5 shrink-0 text-muted" />
            </>
          ) : (
            <>
              <span className="w-3.5 shrink-0" />
              <FileText className="h-3.5 w-3.5 shrink-0 text-muted" />
            </>
          )}
          {mode === 'rename' ? (
            <input
              ref={inputRef}
              value={draft}
              data-testid="wiki-rename-input"
              aria-label={t('contextMenu.wiki.nameLabel')}
              onClick={(e) => e.stopPropagation()}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                e.stopPropagation();
                if (e.key === 'Enter') {
                  e.preventDefault();
                  inputRef.current?.blur();
                } else if (e.key === 'Escape') {
                  e.preventDefault();
                  cancelEdit();
                }
              }}
              onBlur={() => void submitEdit()}
              className="min-w-0 flex-1 rounded border border-primary bg-bg-hover px-1 py-0 text-sm focus:outline-none"
            />
          ) : (
            <span className="truncate">{node.name}</span>
          )}
        </button>
      </ContextMenu>
      {node.is_dir && expanded && (
        <div>
          {mode === 'create' && (
            <div
              className="flex items-center gap-1.5 py-1 pr-2"
              style={{ paddingLeft: `${(depth + 1) * 12 + 8}px` }}
            >
              <FileText className="h-3.5 w-3.5 shrink-0 text-muted" />
              <input
                ref={inputRef}
                value={draft}
                placeholder="name.md"
                data-testid="wiki-new-file-input"
                aria-label={t('contextMenu.wiki.nameLabel')}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  e.stopPropagation();
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    inputRef.current?.blur();
                  } else if (e.key === 'Escape') {
                    e.preventDefault();
                    cancelEdit();
                  }
                }}
                onBlur={() => void submitEdit()}
                className="min-w-0 flex-1 rounded border border-primary bg-bg-hover px-1 py-0 text-sm focus:outline-none"
              />
            </div>
          )}
          {node.children && (
            <div>
              {node.children.map((child) => (
                <TreeNode
                  key={child.path}
                  node={child}
                  depth={depth + 1}
                  selectedFile={selectedFile}
                  onFileClick={onFileClick}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export interface WikiFileTreeAuditInput {
  pageCount: number;
  selectedPagePath: string;
  expandedFolderPaths: string[];
}

export interface WikiFileTreeAuditReport {
  normalizedPageCount: number;
  uniqueExpandedFolderCount: number;
  hasValidSelectedPath: boolean;
  healthy: boolean;
  issueCodes: string[];
}

// eslint-disable-next-line react-refresh/only-export-components
export function evaluateWikiFileTreeGovernanceAudit(
  input: WikiFileTreeAuditInput,
): WikiFileTreeAuditReport {
  const issueCodes: string[] = [];
  if (input.pageCount < 0) {
    issueCodes.push('WIKI_FILE_TREE_PAGE_COUNT_NEGATIVE');
  }
  const trimmedSelected = input.selectedPagePath.trim();
  const hasValidSelectedPath = trimmedSelected.length === 0 || !trimmedSelected.includes('..');
  if (!hasValidSelectedPath) {
    issueCodes.push('WIKI_FILE_TREE_SELECTED_PATH_TRAVERSAL');
  }
  const normalizedFolders = input.expandedFolderPaths
    .map((folder) => folder.trim())
    .filter((folder) => folder.length > 0);
  return {
    normalizedPageCount: Math.max(0, Math.trunc(input.pageCount)),
    uniqueExpandedFolderCount: new Set(normalizedFolders).size,
    hasValidSelectedPath,
    healthy: issueCodes.length === 0,
    issueCodes,
  };
}
