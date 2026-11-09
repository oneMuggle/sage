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
 * not expose a permanent delete action from the management view.
 *
 * Office parity batch 1 (item 1.7): the soft-delete lifecycle is now
 * user-facing. `variant="live"` rows carry 归档 (archive) + 历史版本
 * (snapshots) actions; `variant="archived"` rows carry 恢复 (restore).
 * The destructive delete stays out of the UI.
 *
 * Round 3 (N5): batch operations. Rows in either variant carry a
 * checkbox; a toolbar above the list offers 批量归档 (live) /
 * 批量恢复 (archived) over the selection. The sequential API loop +
 * single refetch live in useOfficeDocuments (batchArchive/batchRestore);
 * this component owns only the selection state, the progress/summary
 * toasts, and clearing the selection after the action. Row-level single
 * actions are unchanged.
 */

import {
  Archive,
  ArchiveRestore,
  ExternalLink,
  FolderOpen,
  FileSpreadsheet,
  FileText,
  History,
  MoreVertical,
  Presentation,
  Save,
  Search,
  X,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';

import type { OfficeDuplicateGroup } from '../../shared/api/officeDuplicateTypes';
import type { OfficeDocType, OfficeDocumentSummary } from '../../shared/api/types';
import { useI18n } from '../../shared/lib/i18n';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '../../shared/ui/DropdownMenu/DropdownMenu';
import { Tooltip } from '../../shared/ui/Tooltip/Tooltip';
import { useTaskCenterStore } from '../task-center/taskCenterStore';

const DOC_TYPE_ICONS: Record<OfficeDocType, React.ReactNode> = {
  ppt: <Presentation className="w-4 h-4" />,
  word: <FileText className="w-4 h-4" />,
  excel: <FileSpreadsheet className="w-4 h-4" />,
  pdf: <FileText className="w-4 h-4" />,
};

const DOC_TYPE_LABELS: Record<OfficeDocType, string> = {
  ppt: 'PPT',
  word: 'Word',
  excel: 'Excel',
  pdf: 'PDF',
};

/** Outcome of a batch archive/restore — drives the summary toast (N5). */
export interface OfficeBatchResult {
  /** Doc ids whose archive/restore succeeded. */
  succeeded: string[];
  /** Doc ids whose archive/restore failed — counted in the summary. */
  failed: string[];
}

export interface OfficeDocumentListProps {
  documents: OfficeDocumentSummary[];
  loading: boolean;
  /** Which slice of the lifecycle this list renders — drives the row actions. */
  variant?: 'live' | 'archived';
  /** Native Save As dialog → copy managed file to chosen path. */
  onSaveAs?: (docId: string) => void | Promise<void>;
  /** shell.openPath on the managed file. */
  onOpen?: (docId: string) => void | Promise<void>;
  /** shell.showItemInFolder on the managed file. */
  onShowInFolder?: (docId: string) => void | Promise<void>;
  /** Soft-delete the row (variant="live" only). */
  onArchive?: (docId: string) => void | Promise<void>;
  /** Un-archive the row (variant="archived" only). */
  onRestore?: (docId: string) => void | Promise<void>;
  /** Open the 历史版本 (snapshots) panel for the row. */
  onViewSnapshots?: (docId: string) => void | Promise<void>;
  /**
   * M1 (Phase 0): 点击行加载预览。整行可点击/可键盘聚焦（Enter/Space），
   * 与右侧图标按钮并存；点击操作按钮不触发预览。
   */
  onPreview?: (docId: string) => void | Promise<void>;
  /**
   * Batch-archive the selected live rows (round-3 N5, variant="live").
   * Resolves with the per-item outcome so the toolbar can show a
   * counted summary toast. When absent the checkboxes/toolbar hide.
   */
  onBatchArchive?: (docIds: string[]) => OfficeBatchResult | Promise<OfficeBatchResult>;
  /**
   * Batch-restore the selected archived rows (round-3 N5,
   * variant="archived"). Same contract as onBatchArchive.
   */
  onBatchRestore?: (docIds: string[]) => OfficeBatchResult | Promise<OfficeBatchResult>;

  /** ── T3: 文档库搜索/筛选/排序 (Item A) ─────────────────── */
  /** Current search text (filename substring). */
  q?: string;
  /** Called when the search input changes. */
  onQChange?: (next: string) => void;
  /** Current doc_type filter ('' = all). */
  docType?: string;
  /** Called when the type filter changes. */
  onDocTypeChange?: (next: string) => void;
  /** Current sort key ('' = backend default = updated_desc). */
  sort?: string;
  /** Called when the sort dropdown changes. */
  onSortChange?: (next: string) => void;

  /** ── T4: 重复组 (Item A) ─────────────────────────────── */
  /** Duplicate groups loaded for the current workspace. */
  duplicateGroups?: ReadonlyArray<OfficeDuplicateGroup>;
  /** Called when the "Clean up duplicates" banner is clicked. */
  onArchiveAllButNewest?: (group: OfficeDuplicateGroup) => void | Promise<unknown>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatOfficeDocumentListMarkdown(
  documents: ReadonlyArray<OfficeDocumentSummary>,
  variant: 'live' | 'archived' = 'live',
): string {
  const lines = [
    '# Office 文档历史列表 (Office Document List)',
    '',
    `- **视图类型**: ${variant === 'archived' ? '已归档 (archived)' : '当前活跃 (live)'}`,
    `- **文档总数**: ${documents.length}`,
  ];
  if (documents.length === 0) {
    lines.push('', '_暂无历史文档_');
  } else {
    lines.push('', '## 文档明细');
    for (const doc of documents) {
      const name = doc.original_filename ?? doc.generated_filename ?? doc.id;
      lines.push(
        `- **${name}** (\`${doc.id}\`, ${DOC_TYPE_LABELS[doc.doc_type]}, ${doc.status}, ${(doc.metadata.file_size_bytes / 1024).toFixed(1)} KB)`,
      );
    }
  }
  return lines.join('\n');
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatOfficeDocumentListJson(
  documents: ReadonlyArray<OfficeDocumentSummary>,
  variant: 'live' | 'archived' = 'live',
): string {
  return JSON.stringify(
    {
      exportedAt: new Date().toISOString(),
      variant,
      total: documents.length,
      documents,
    },
    null,
    2,
  );
}

export function OfficeDocumentList({
  documents,
  loading,
  variant = 'live',
  onSaveAs,
  onOpen,
  onShowInFolder,
  onArchive,
  onRestore,
  onViewSnapshots,
  onPreview,
  onBatchArchive,
  onBatchRestore,
  q = '',
  onQChange,
  docType = '',
  onDocTypeChange,
  sort = '',
  onSortChange,
  duplicateGroups = [],
  onArchiveAllButNewest,
}: OfficeDocumentListProps) {
  const { t } = useI18n();
  // Round-3 N5: selection state for the batch actions. All hooks stay
  // above the loading/empty early returns (rules-of-hooks).
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [batchBusy, setBatchBusy] = useState(false);

  // T4: flatten duplicate groups to a Set of doc ids for O(1) badge lookup
  // in the row. All groups except the newest doc (index 0) are duplicates.
  const duplicateDocIds = useMemo(() => {
    const ids = new Set<string>();
    for (const group of duplicateGroups) {
      // Backend returns groups ordered newest-first; skip the first (keep).
      for (let i = 1; i < group.documents.length; i++) {
        ids.add(group.documents[i].id);
      }
    }
    return ids;
  }, [duplicateGroups]);

  // Prune ids that left the current slice — the parent refetches after
  // every action, and the live↔archived toggle reuses this component
  // instance with a different documents array.
  useEffect(() => {
    setSelected((prev) => {
      if (prev.size === 0) return prev;
      const ids = new Set(documents.map((d) => d.id));
      const next = new Set([...prev].filter((id) => ids.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [documents]);

  const batchAction = variant === 'archived' ? onBatchRestore : onBatchArchive;

  const toggleDoc = (docId: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(docId)) {
        next.delete(docId);
      } else {
        next.add(docId);
      }
      return next;
    });
  };

  const allSelected = documents.length > 0 && documents.every((d) => selected.has(d.id));
  const toggleAll = () => {
    setSelected(allSelected ? new Set() : new Set(documents.map((d) => d.id)));
  };

  const handleBatch = async () => {
    if (!batchAction || selected.size === 0 || batchBusy) return;
    // Freeze the selection up front — the refetch inside batchAction
    // prunes `selected` via the effect above.
    const docIds = [...selected];
    setBatchBusy(true);
    // Progress toast: the same toast id transitions 开始… → 完成 N 项.
    const toastId = toast.loading(t('office.batch.start'));
    try {
      const { succeeded, failed } = await batchAction(docIds);
      if (failed.length === 0) {
        toast.success(t('office.batch.done').replace('{n}', String(succeeded.length)), {
          id: toastId,
        });
      } else {
        toast.error(
          t('office.batch.doneWithFailures')
            .replace('{n}', String(succeeded.length))
            .replace('{m}', String(failed.length)),
          { id: toastId },
        );
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`${t('office.batch.failed')}: ${msg}`, { id: toastId });
    } finally {
      setBatchBusy(false);
      // Clear the selection after the action regardless of outcome —
      // failed rows are reported in the summary and can be retried via
      // the per-row action.
      setSelected(new Set());
    }
  };

  // Status labels are built inside the component so the translated
  // strings track the active locale (module-level maps can't call t()).
  const statusLabels: Record<OfficeDocumentSummary['status'], string> = {
    parsed: t('office.doc.status.parsed'),
    generated: t('office.doc.status.generated'),
    edited: t('office.doc.status.edited'),
  };

  // P11: 任务中心 office 任务跳转后，定位并高亮对应文档行（8s 自动清除）。
  const pendingHighlight = useTaskCenterStore((s) => s.pendingHighlight);
  const clearHighlight = useTaskCenterStore((s) => s.clearHighlight);
  const highlightDocName = pendingHighlight?.docName ?? null;
  const [highlightUntil, setHighlightUntil] = useState(0);
  const highlightRef = useRef<HTMLLIElement | null>(null);

  useEffect(() => {
    if (!highlightDocName) return;
    setHighlightUntil(Date.now() + 8000);
    const timer = setTimeout(() => {
      setHighlightUntil(0);
      clearHighlight();
    }, 8000);
    return () => clearTimeout(timer);
  }, [highlightDocName, clearHighlight]);

  const highlightedId = (() => {
    if (Date.now() > highlightUntil || !highlightDocName) return null;
    const hit = documents.find(
      (doc) =>
        doc.generated_filename === highlightDocName ||
        doc.original_filename === highlightDocName ||
        (doc.generated_filename ?? '').startsWith(`${highlightDocName}.`),
    );
    return hit?.id ?? null;
  })();

  useEffect(() => {
    if (highlightedId) {
      highlightRef.current?.scrollIntoView({ block: 'nearest' });
    }
  }, [highlightedId]);

  if (loading) {
    // P2: 加载态从纯文字升级为骨架行（对齐 LoadingState skeleton 约定）
    return (
      <div className="p-3 space-y-2" data-testid="office-doc-list-skeleton">
        {[0, 1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-10 rounded bg-line animate-pulse"
            style={{ width: `${100 - i * 7}%` }}
          />
        ))}
      </div>
    );
  }
  if (documents.length === 0) {
    return (
      <div className="text-sm text-muted p-4 text-center border border-dashed border-border rounded-lg">
        {t('office.doc.empty')}
      </div>
    );
  }

  const batchLabel = variant === 'archived' ? t('office.batch.restore') : t('office.batch.archive');
  const batchTestId = variant === 'archived' ? 'office-batch-restore' : 'office-batch-archive';

  /* v8 ignore start */

  /* v8 ignore stop */

  return (
    <div>
      {/* T3: search/filter/sort toolbar (Item A). Hidden entirely when no
          callbacks are wired — keeps tests and callers without filters clean. */}
      {(onQChange || onDocTypeChange || onSortChange) && (
        <div className="mb-2 flex items-center gap-2 text-ui-xs">
          {onQChange && (
            <div className="relative flex-1 max-w-xs">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted" />
              <input
                type="text"
                value={q}
                onChange={(e) => onQChange(e.target.value)}
                placeholder={t('office.doclib.search')}
                data-testid="office-doclib-search"
                className="w-full pl-7 pr-7 py-1.5 text-sm border border-border rounded bg-surface focus:outline-none focus:border-primary"
              />
              {q.length > 0 && (
                <button
                  type="button"
                  onClick={() => onQChange('')}
                  data-testid="office-doclib-search-clear"
                  aria-label={t('office.doclib.searchClear')}
                  className="absolute right-1.5 top-1/2 -translate-y-1/2 text-muted hover:text-text"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
          )}
          {onDocTypeChange && (
            <select
              value={docType}
              onChange={(e) => onDocTypeChange(e.target.value)}
              data-testid="office-doclib-filter-type"
              className="px-2 py-1.5 text-sm border border-border rounded bg-surface focus:outline-none focus:border-primary"
            >
              <option value="">{t('office.doclib.filter.allTypes')}</option>
              <option value="word">Word</option>
              <option value="excel">Excel</option>
              <option value="ppt">PPT</option>
              <option value="pdf">PDF</option>
            </select>
          )}
          {onSortChange && (
            <select
              value={sort}
              onChange={(e) => onSortChange(e.target.value)}
              data-testid="office-doclib-sort"
              className="px-2 py-1.5 text-sm border border-border rounded bg-surface focus:outline-none focus:border-primary"
            >
              <option value="-updated_at">{t('office.doclib.sort.updatedDesc')}</option>
              <option value="updated_at">{t('office.doclib.sort.updatedAsc')}</option>
              <option value="-created_at">{t('office.doclib.sort.createdDesc')}</option>
              <option value="name">{t('office.doclib.sort.nameAsc')}</option>
              <option value="-name">{t('office.doclib.sort.nameDesc')}</option>
              <option value="-size">{t('office.doclib.sort.sizeDesc')}</option>
              <option value="size">{t('office.doclib.sort.sizeAsc')}</option>
            </select>
          )}
        </div>
      )}
      {/* T4: duplicate banner (Item A). Shown only on the live view when
          duplicate groups were loaded. Each group gets its own cleanup button. */}
      {variant === 'live' && onArchiveAllButNewest && duplicateGroups.length > 0 && (
        <div
          className="mb-2 p-2 rounded border border-amber-400/40 bg-amber-50 dark:bg-amber-950/20 text-xs text-text"
          data-testid="office-duplicate-banner"
        >
          <div className="flex items-center justify-between gap-2">
            <div>
              <div className="flex items-center gap-1.5 font-medium">
                <span>⚠</span>
                <span>
                  {t('office.doclib.duplicateBanner').replace(
                    '{n}',
                    String(duplicateGroups.length),
                  )}
                </span>
              </div>
              <div className="text-muted mt-0.5">{t('office.doclib.duplicateBannerHint')}</div>
            </div>
            <button
              type="button"
              onClick={() => {
                void (async () => {
                  for (const group of duplicateGroups) {
                    try {
                      await onArchiveAllButNewest(group);
                    } catch {
                      toast.error(t('office.doclib.duplicateCleanupFailed'));
                      return;
                    }
                  }
                  // Count total archived duplicates across all groups.
                  const total = duplicateGroups.reduce(
                    (acc, g) => acc + Math.max(0, g.documents.length - 1),
                    0,
                  );
                  toast.success(
                    t('office.doclib.duplicateCleanupDone').replace('{n}', String(total)),
                  );
                })();
              }}
              data-testid="office-duplicate-cleanup-all"
              className="px-3 py-1.5 rounded text-sm border border-amber-500 text-amber-700 dark:text-amber-300 hover:bg-amber-500/10 whitespace-nowrap"
            >
              {t('office.doclib.duplicateCleanup')}
            </button>
          </div>
        </div>
      )}
      {batchAction && (
        <div className="flex items-center gap-3 mb-2" data-testid="office-batch-bar">
          <label className="flex items-center gap-1.5 text-xs text-muted cursor-pointer">
            <input
              type="checkbox"
              checked={allSelected}
              onChange={toggleAll}
              disabled={batchBusy}
              data-testid="office-batch-select-all"
              aria-label={t('office.batch.selectAll')}
              className="w-4 h-4"
            />
            {t('office.batch.selectAll')}
          </label>
          <span className="text-xs text-muted" data-testid="office-batch-count">
            {t('office.batch.selectedCount').replace('{n}', String(selected.size))}
          </span>
          <button
            type="button"
            onClick={() => void handleBatch()}
            disabled={selected.size === 0 || batchBusy}
            data-testid={batchTestId}
            className="ml-auto px-3 py-1.5 rounded text-sm border border-primary text-primary hover:bg-primary/10 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {batchLabel}
          </button>
        </div>
      )}
      <ul className="space-y-1.5" data-testid="office-document-list">
        {documents.map((doc) => {
          const filename = doc.original_filename ?? doc.generated_filename ?? doc.id;
          const isArchived = variant === 'archived';
          // Live rows surface "open" (external) as the inline primary action;
          // archived rows surface "restore". Everything else lives in the
          // hover-revealed ⋯ menu — see plan §Section 2 for the layout spec.
          // At least one menu entry will render — otherwise the ⋯ trigger has
          // no purpose and we'd render an empty menu for no reason.
          const menuEntries = [
            !isArchived && onViewSnapshots && 'snapshots',
            onShowInFolder && 'showInFolder',
            !isArchived && onSaveAs && 'saveAs',
            !isArchived && onOpen && 'open',
            !isArchived && onArchive && 'archive',
            isArchived && onOpen && 'open',
          ].filter(Boolean) as string[];
          const hasMenu = menuEntries.length > 0;

          return (
            <li
              key={doc.id}
              ref={doc.id === highlightedId ? highlightRef : undefined}
              onClick={onPreview ? () => void onPreview(doc.id) : undefined}
              data-testid={doc.id === highlightedId ? 'office-doc-highlighted' : undefined}
              className={`group flex items-center gap-2 px-2 py-1.5 border border-border rounded-lg bg-surface ${
                onPreview ? 'cursor-pointer hover:bg-bg-hover transition-colors' : ''
              } ${doc.id === highlightedId ? 'ring-2 ring-primary bg-primary/5' : ''}`}
            >
              {batchAction && (
                <input
                  type="checkbox"
                  checked={selected.has(doc.id)}
                  onChange={() => toggleDoc(doc.id)}
                  onClick={(event) => event.stopPropagation()}
                  disabled={batchBusy}
                  data-testid={`office-doc-select-${doc.id}`}
                  aria-label={t('office.batch.selectRow')}
                  className="w-4 h-4 shrink-0"
                />
              )}
              <div className="shrink-0 text-muted pointer-events-none">
                {DOC_TYPE_ICONS[doc.doc_type]}
              </div>
              {/*
                Filename control. `min-w-0` lets the inner truncate shrink;
                the tooltip reveals the full name when the row is too narrow.
              */}
              <Tooltip content={filename}>
                <button
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation();
                    void onPreview?.(doc.id);
                  }}
                  disabled={!onPreview}
                  className="flex-1 min-w-0 text-left disabled:cursor-default"
                  data-testid={`office-doc-open-${doc.id}`}
                >
                  <div className="text-sm font-medium text-text truncate">{filename}</div>
                  <div className="flex items-center gap-1.5 text-xs text-muted min-w-0">
                    <span className="shrink-0">{DOC_TYPE_LABELS[doc.doc_type]}</span>
                    <span aria-hidden>·</span>
                    <span className="shrink-0">{statusLabels[doc.status]}</span>
                    <span aria-hidden>·</span>
                    <span className="shrink-0">
                      {(doc.metadata.file_size_bytes / 1024).toFixed(1)} KB
                    </span>
                    <span aria-hidden>·</span>
                    <span className="truncate">{new Date(doc.created_at).toLocaleString()}</span>
                    {doc.archived_at != null && (
                      <>
                        <span aria-hidden>·</span>
                        <span className="shrink-0">
                          {t('office.doc.archivedAt')} {new Date(doc.archived_at).toLocaleString()}
                        </span>
                      </>
                    )}
                    {/* T4: "重复" badge when this doc is the older copy in a duplicate group (Item A). */}
                    {duplicateDocIds.has(doc.id) && (
                      <span className="shrink-0 px-1 py-0.5 text-ui-xs rounded bg-amber-400/20 text-amber-700 dark:text-amber-300 border border-amber-400/40">
                        {t('office.doclib.duplicateBadge')}
                      </span>
                    )}
                  </div>
                </button>
              </Tooltip>
              {/*
                Action cluster — `shrink-0` prevents the buttons from being
                squeezed by the filename flex-1. Only the primary inline
                action stays visible; the rest collapse behind ⋯.
              */}
              <div
                className="flex items-center shrink-0"
                onClick={(event) => event.stopPropagation()}
              >
                {!isArchived && onOpen && (
                  <button
                    type="button"
                    onClick={() => void onOpen(doc.id)}
                    className="p-1 rounded text-muted hover:text-primary hover:bg-primary/10 transition-colors"
                    aria-label={t('office.doc.open')}
                    data-testid={`office-doc-inline-open-${doc.id}`}
                  >
                    <ExternalLink className="w-4 h-4" />
                  </button>
                )}
                {isArchived && onRestore && (
                  <button
                    type="button"
                    onClick={() => void onRestore(doc.id)}
                    className="p-1 rounded text-muted hover:text-primary hover:bg-primary/10 transition-colors"
                    aria-label={t('office.doc.restore')}
                    data-testid={`office-doc-inline-restore-${doc.id}`}
                  >
                    <ArchiveRestore className="w-4 h-4" />
                  </button>
                )}
                {hasMenu && (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <button
                        type="button"
                        aria-label={t('office.doclib.moreActions')}
                        data-testid={`office-doc-more-${doc.id}`}
                        className="p-1 rounded text-muted opacity-0 transition-opacity duration-150 group-hover:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100 hover:bg-surface-hover hover:text-text"
                      >
                        <MoreVertical className="w-4 h-4" />
                      </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      {variant === 'live' && onViewSnapshots && (
                        <DropdownMenuItem onSelect={() => void onViewSnapshots(doc.id)}>
                          <History className="mr-2 h-4 w-4" />
                          {t('office.doc.snapshots')}
                        </DropdownMenuItem>
                      )}
                      {onShowInFolder && (
                        <DropdownMenuItem onSelect={() => void onShowInFolder(doc.id)}>
                          <FolderOpen className="mr-2 h-4 w-4" />
                          {t('office.doc.showInFolder')}
                        </DropdownMenuItem>
                      )}
                      {variant === 'live' && onOpen && (
                        <DropdownMenuItem onSelect={() => void onOpen(doc.id)}>
                          <ExternalLink className="mr-2 h-4 w-4" />
                          {t('office.doc.open')}
                        </DropdownMenuItem>
                      )}
                      {variant === 'live' && onSaveAs && (
                        <DropdownMenuItem onSelect={() => void onSaveAs(doc.id)}>
                          <Save className="mr-2 h-4 w-4" />
                          {t('office.doc.saveAs')}
                        </DropdownMenuItem>
                      )}
                      {variant === 'live' && onArchive && (
                        <DropdownMenuItem
                          variant="destructive"
                          onSelect={() => void onArchive(doc.id)}
                        >
                          <Archive className="mr-2 h-4 w-4" />
                          {t('office.doc.archive')}
                        </DropdownMenuItem>
                      )}
                    </DropdownMenuContent>
                  </DropdownMenu>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditOfficeDocumentListGovernance(): {
  moduleId: string;
  phase: string;
  status: 'ready';
} {
  return {
    moduleId: 'src/features/office/OfficeDocumentList.tsx',
    phase: 'P164',
    status: 'ready',
  };
}
