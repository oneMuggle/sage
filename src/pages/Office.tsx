/**
 * /office page — 2026-11 信息架构整理版。
 *
 * 结构：
 *   ┌──────────────────────────────────────────┐
 *   │ Header: H1 "文档工作台" + [环境] + 工作区 │
 *   ├──────────────────────────────────────────┤
 *   │ 顶层 Tabs (4 个任务域, keep-alive):      │
 *   │   [文档] [文档生成] [规则] [LaTeX]       │
 *   ├──────────────────────────────────────────┤
 *   │ 当前 tab 的内容 (lazy + forceMount)       │
 *   └──────────────────────────────────────────┘
 *
 * 与原版本相比：
 *   - OfficeCapabilityBar / OfficeStagingInspector 收进页头 [环境] 浮层；
 *   - 7 个 LaTeX 面板收进 latex tab 内 3 个子 tab；
 *   - JournalPanel 收进 generate tab 的可折叠 <details>；
 *   - WordRuleExtractionPanel 移到 rules tab；
 *   - 通过 URL search params 驱动 tab / 子 tab，支持深度链接。
 *
 * 保留不变：
 *   - 工作区绑定流程 (useCurrentWorkspace + WorkspaceBindModal)；
 *   - 文件预览 + 编辑 + 归档/恢复/批量操作的完整链路；
 *   - `auditOfficePageGovernance` 导出（Help 页 P142 检查依赖）。
 */

import { FolderOpen } from 'lucide-react';
import { useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';

import { useWorkspaceContext } from '../app/providers/SessionWorkspaceProvider';
import { JournalPanel } from '../features/journal';
import {
  OfficeDocumentList,
  OfficeDuplicateDialog,
  OfficeEditPreviewDialog,
  OfficeGenerateForm,
  OfficeSnapshotPanel,
  useOfficeDocuments,
  type OfficeListView,
  type OfficeMultiImportResult,
  type OfficePreviewData,
  type OfficeReadResult,
} from '../features/office';
import { OfficeAiAssistantPanel } from '../features/office/OfficeAiAssistantPanel';
import { OfficeSpecLibrary } from '../features/office/OfficeSpecLibrary';
import { WordBatchAuditPanel } from '../features/office/WordBatchAuditPanel';
import { WordRuleExtractionPanel } from '../features/office/WordRuleExtractionPanel';
import { DocumentCanvas } from '../features/office/canvas/DocumentCanvas';
import { pdfAvailableForDocument } from '../features/office/officeCapabilities';
import { OfficeAiSidebarHost } from '../features/office/sidebar/OfficeAiSidebarHost';
import type { QuickActionTab } from '../features/office/sidebar/QuickActions';
import { WorkspaceBindModal } from '../features/workspace';
import type { OfficeCapabilities, OfficeDocType } from '../shared/api/types';
import { fillTemplate } from '../shared/lib/fillTemplate';
import { useI18n, type TranslationKey } from '../shared/lib/i18n';
import { useCurrentWorkspace } from '../shared/lib/workspaceContext';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../shared/ui/Tabs';

import { OfficeEnvironmentButton } from './office/OfficeEnvironmentButton';
import { OfficeLatexTab } from './office/OfficeLatexTab';
import { OfficeLayout } from './office/OfficeLayout';
import {
  DEFAULT_OFFICE_LATEX_TAB,
  DEFAULT_OFFICE_TAB,
  OFFICE_LATEX_PARAM,
  OFFICE_TAB_IDS,
  OFFICE_TAB_PARAM,
  parseOfficeLatexTab,
  parseOfficeTab,
  useKeepAliveTabs,
  type OfficeLatexTabId,
  type OfficeTabId,
} from './office/officeTabs';

const TOP_TAB_LABEL_KEYS: Record<OfficeTabId, TranslationKey> = {
  documents: 'office.tab.documents',
  generate: 'office.tab.generate',
  rules: 'office.tab.rules',
  latex: 'office.tab.latex',
};

export function Office() {
  const { t } = useI18n();
  const workspacePath = useCurrentWorkspace() ?? null;
  const { bind, revoke, status: workspaceStatus, error: workspaceError } = useWorkspaceContext();
  const [searchParams, setSearchParams] = useSearchParams();

  // URL search params 是 tab / 子 tab 的单一事实来源。缺失或非法值走默认，
  // 这样旧书签、手工编辑 URL 都能落到可用 tab 而不是空白面板。
  const activeTab: OfficeTabId = parseOfficeTab(searchParams.get(OFFICE_TAB_PARAM));
  const activeLatexTab: OfficeLatexTabId = parseOfficeLatexTab(
    searchParams.get(OFFICE_LATEX_PARAM),
  );
  const mounted = useKeepAliveTabs(activeTab);

  // 切到非 latex 顶层 tab 时，latex 子 tab 参数从 URL 里清掉，避免
  // 用户回到 latex 时被一个"不属于当前分区"的旧子 tab 值干扰。
  const setTab = (next: OfficeTabId) => {
    setSearchParams(
      (prev) => {
        const updated = new URLSearchParams(prev);
        if (next === DEFAULT_OFFICE_TAB) updated.delete(OFFICE_TAB_PARAM);
        else updated.set(OFFICE_TAB_PARAM, next);
        if (next !== 'latex') updated.delete(OFFICE_LATEX_PARAM);
        return updated;
      },
      { replace: true },
    );
  };

  // LaTeX 子 tab 切换同时把顶层 tab 锁到 'latex'，保证 URL 一致性。
  const setLatexTab = (next: OfficeLatexTabId) => {
    setSearchParams(
      (prev) => {
        const updated = new URLSearchParams(prev);
        updated.set(OFFICE_TAB_PARAM, 'latex');
        if (next === DEFAULT_OFFICE_LATEX_TAB) updated.delete(OFFICE_LATEX_PARAM);
        else updated.set(OFFICE_LATEX_PARAM, next);
        return updated;
      },
      { replace: true },
    );
  };

  // Task 5: workspacePath now comes from SessionWorkspaceProvider, not
  // local state. AppProviders mounts the provider; Chat.tsx reads from
  // the same context. `?? null` keeps the local consumer contract
  // (which expects `string | null`) unchanged.
  const [preview, setPreview] = useState<OfficePreviewData | null>(null);
  // HIGH FIX: stale-read guard. Increments on every handleImportAndRead
  // invocation; setPreview checks the captured id before applying state.
  const readIdRef = useRef(0);

  const [isBindModalOpen, setIsBindModalOpen] = useState(false);
  // 浮层里的 OfficeCapabilityBar 通过回调把探测结果推到父组件，
  // 预览面板据此决定是否显示"高保真"导出开关。
  const [capabilities, setCapabilities] = useState<OfficeCapabilities | null>(null);

  const {
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
    archiveAllButNewest,
    importAndReadMulti,
    readDroppedMulti,
    saveAs,
    open,
    showInFolder,
    archiveDocument,
    restoreDocument,
    batchArchive,
    batchRestore,
    readDocument,
    pendingDuplicate,
    resolvePendingDuplicate,
  } = useOfficeDocuments(workspacePath);

  // Item 1.7: 历史版本 panel
  const [snapshotDocId, setSnapshotDocId] = useState<string | null>(null);
  const snapshotDoc = snapshotDocId ? documents.find((d) => d.id === snapshotDocId) : undefined;

  // Item 2.5: 编辑预览 dialog
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const editDoc = preview ? preview.data.summary : null;
  const editSheetNames =
    preview?.docType === 'excel' ? preview.data.sheets.map((s) => s.name) : undefined;

  // The bind modal owns its own IPC; we just need to know when the
  // workspace has actually changed so the stale-read guard can drop any
  // in-flight read from the previous workspace.
  const handleBindModalClose = () => {
    setIsBindModalOpen(false);
    readIdRef.current += 1;
    setPreview(null);
    setEditDialogOpen(false);
  };

  const toPreview = (docType: OfficeDocType, data: OfficeReadResult): OfficePreviewData => ({
    docType,
    data: data as never,
  });

  // 多文件导入的两个入口（文件选择器 / 拖拽）共享结果后处理：先预览第一个
  // 成功导入的文档，再刷新列表并汇总 toast。选择「打开已有文档」的文件没有
  // 重新导入，因此单独提示；它们不计入 intakePartial 的 skipped 数。
  const settleMultiImport = async (result: OfficeMultiImportResult, myReadId: number) => {
    if (myReadId !== readIdRef.current) return;

    for (const existing of result.openedExisting) {
      toast.info(
        fillTemplate(t('office.toast.duplicateOpened'), {
          filename: existing.original_filename ?? existing.generated_filename,
        }),
      );
    }

    const first = result.imported[0];
    if (first) setPreview(toPreview(first.docType, first.readResult));

    await refresh();
    if (myReadId !== readIdRef.current) return;

    const importedCount = result.imported.length;
    const openedCount = result.openedExisting.length;
    const failedCount = result.skipped.length - openedCount;
    if (importedCount === 0 && openedCount === 0) {
      toast.error(t('office.toast.intakeNothingImported'));
      return;
    }
    if (failedCount > 0) {
      toast.warning(
        fillTemplate(t('office.toast.intakePartial'), {
          imported: importedCount,
          skipped: failedCount,
        }),
      );
    } else if (importedCount > 1) {
      toast.success(fillTemplate(t('office.toast.intakeMultiSuccess'), { count: importedCount }));
    } else if (importedCount === 1) {
      toast.success(t('office.toast.readSuccess'));
    }

    // 整批都是「打开已有文档」时没有新导入的文档，把最后打开的已有文档
    // 加载进预览面板，而不是留下空白预览。
    const existingPreview = result.openedExisting[result.openedExisting.length - 1];
    if (!first && existingPreview) {
      const existingReadId = ++readIdRef.current;
      try {
        const data = await readDocument(existingPreview.id);
        if (existingReadId !== readIdRef.current) return;
        setPreview(toPreview(existingPreview.doc_type, data));
      } catch (e) {
        if (existingReadId !== readIdRef.current) return;
        const msg = e instanceof Error ? e.message : String(e);
        toast.error(`${t('office.toast.readFailed')}: ${msg}`);
      }
    }
  };

  // Phase 0 (plan §M1): 单一导入入口，多文件。第一个成功导入的文档更新预览，
  // 其他文件仅触发列表刷新；错误用聚合 toast 一次性展示。
  const handleImportAndReadMulti = async () => {
    if (!workspacePath) {
      toast.error(t('office.toast.selectWorkspace'));
      return;
    }
    const myReadId = ++readIdRef.current;
    setEditDialogOpen(false);
    try {
      const result = await importAndReadMulti();
      if (!result) return;
      await settleMultiImport(result, myReadId);
    } catch (e) {
      if (myReadId !== readIdRef.current) return;
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`${t('office.toast.readFailed')}: ${msg}`);
      setPreview(null);
    }
  };

  const handleReadDroppedMulti = async (sourcePaths: string[]) => {
    if (!workspacePath) {
      toast.error(t('office.toast.selectWorkspace'));
      return;
    }
    const myReadId = ++readIdRef.current;
    setEditDialogOpen(false);
    try {
      const result = await readDroppedMulti(sourcePaths);
      await settleMultiImport(result, myReadId);
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
      if (savedPath) toast.success(`${t('office.toast.savedAs')} ${savedPath}`);
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

  const handleArchive = async (docId: string) => {
    try {
      await archiveDocument(docId);
      toast.success(t('office.toast.archived'));
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`${t('office.toast.archiveFailed')}: ${msg}`);
    }
  };

  const handleRestore = async (docId: string) => {
    try {
      await restoreDocument(docId);
      toast.success(t('office.toast.restored'));
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`${t('office.toast.restoreFailed')}: ${msg}`);
    }
  };

  const handleSnapshotRestored = async (docId: string) => {
    const doc = documents.find((d) => d.id === docId);
    await refresh();
    if (!doc) return;
    const myReadId = ++readIdRef.current;
    try {
      const data = await readDocument(docId);
      if (myReadId !== readIdRef.current) return;
      setPreview(toPreview(doc.doc_type, data));
    } catch (e) {
      if (myReadId !== readIdRef.current) return;
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`${t('office.toast.readFailed')}: ${msg}`);
    }
  };

  // M1 (Phase 0): 历史列表行点击 → 加载文档到预览面板。复用 readDocument
  // 读取受管路径，与快照恢复/编辑应用同一 stale-read guard，避免切文档时
  // 旧结果覆盖新预览。
  const handlePreviewDocument = async (docId: string) => {
    const doc = documents.find((d) => d.id === docId);
    if (!doc) return;
    const myReadId = ++readIdRef.current;
    setEditDialogOpen(false);
    try {
      const data = await readDocument(docId);
      if (myReadId !== readIdRef.current) return;
      setPreview(toPreview(doc.doc_type, data));
    } catch (e) {
      if (myReadId !== readIdRef.current) return;
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`${t('office.toast.readFailed')}: ${msg}`);
      setPreview(null);
    }
  };

  const handleEditApplied = async (docId: string) => {
    const doc = documents.find((d) => d.id === docId);
    await refresh();
    if (!doc) return;
    const myReadId = ++readIdRef.current;
    try {
      const data = await readDocument(docId);
      if (myReadId !== readIdRef.current) return;
      setPreview(toPreview(doc.doc_type, data));
    } catch (e) {
      if (myReadId !== readIdRef.current) return;
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`${t('office.toast.readFailed')}: ${msg}`);
    }
  };

  // 文档 tab：左侧文档库（列表 + 快照），中栏文档画布（导入 / 预览 + 编辑对话框）。
  const renderDocumentsTab = () => (
    <div className="space-y-6">
      {error && (
        <div className="px-4 py-3 bg-error/10 border border-error/30 rounded text-sm text-error">
          {error}
        </div>
      )}

      <OfficeLayout
        left={
          <>
            {/* Document list — live / archived toggle */}
            <div className="flex items-center gap-3 mb-3">
              <h2 className="text-sm font-medium text-text-secondary">
                {t('office.section.library')} ({documents.length})
              </h2>
              <div className="ml-auto flex gap-2">
                {(
                  [
                    ['live', t('office.view.live')],
                    ['archived', t('office.view.archived')],
                  ] as [OfficeListView, string][]
                ).map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setView(value)}
                    data-testid={`office-view-${value}`}
                    className={[
                      'px-3 py-1.5 rounded text-sm border',
                      view === value
                        ? 'border-primary bg-primary/10 text-primary'
                        : 'border-border text-text-secondary hover:bg-bg-hover',
                    ].join(' ')}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
            <OfficeDocumentList
              documents={documents}
              loading={loading}
              variant={view}
              onSaveAs={handleSaveAs}
              onOpen={handleOpen}
              onShowInFolder={handleShowInFolder}
              onArchive={handleArchive}
              onRestore={handleRestore}
              onViewSnapshots={(docId) => setSnapshotDocId(docId)}
              onPreview={handlePreviewDocument}
              onBatchArchive={batchArchive}
              onBatchRestore={batchRestore}
              q={q}
              onQChange={setQ}
              docType={docType}
              onDocTypeChange={setDocType}
              sort={sort}
              onSortChange={setSort}
              duplicateGroups={duplicateGroups}
              onArchiveAllButNewest={archiveAllButNewest}
            />
            {snapshotDoc && (
              <div className="mt-3">
                <OfficeSnapshotPanel
                  doc={snapshotDoc}
                  onClose={() => setSnapshotDocId(null)}
                  onRestored={handleSnapshotRestored}
                />
              </div>
            )}
          </>
        }
        center={
          <>
            <h2 className="text-sm font-medium text-text-secondary mb-3">
              {t('office.section.canvas')}
            </h2>
            <DocumentCanvas
              preview={preview}
              workspacePath={workspacePath}
              onPick={handleImportAndReadMulti}
              onDropFiles={handleReadDroppedMulti}
              onEditPreview={
                preview && preview.docType !== 'pdf' ? () => setEditDialogOpen(true) : undefined
              }
              fidelityAvailable={pdfAvailableForDocument(capabilities, preview?.docType)}
              onRefresh={() => void refresh()}
              disabled={loading}
            />
            {editDialogOpen && editDoc && preview?.docType !== 'pdf' && (
              <div className="mt-3">
                <OfficeEditPreviewDialog
                  workspacePath={workspacePath ?? ''}
                  doc={editDoc}
                  sheetNames={editSheetNames}
                  onApplied={handleEditApplied}
                  onClose={() => setEditDialogOpen(false)}
                />
              </div>
            )}
          </>
        }
      />
    </div>
  );

  const renderGenerateTab = () => (
    <div className="space-y-6">
      <OfficeGenerateForm workspacePath={workspacePath ?? ''} onGenerated={refresh} />

      {/* JournalPanel 从原来的顶层独立面板折叠到 <details> 内，
          与"生成新文档"共享同一个任务域但不再占用首屏空间。 */}
      <details className="rounded-lg border border-border bg-bg-subtle">
        <summary className="cursor-pointer select-none list-none px-4 py-3 flex items-center justify-between">
          <div>
            <h3 className="text-sm font-medium text-text">{t('office.generate.journal.title')}</h3>
            <p className="text-xs text-muted mt-0.5">{t('office.generate.journal.hint')}</p>
          </div>
          <span className="text-xs text-text-secondary">▶</span>
        </summary>
        <div className="border-t border-border">
          <JournalPanel />
        </div>
      </details>
    </div>
  );

  const renderRulesTab = () => (
    <div className="space-y-4">
      {/* M2.5: 格式规范书库（工作区默认 / 文档级绑定 / 从说明文件提取）。 */}
      <OfficeSpecLibrary workspacePath={workspacePath} />

      {/* M3: 规范书规则 + LLM 语义建议的合并审校。 */}
      <OfficeAiAssistantPanel workspacePath={workspacePath} />

      <WordRuleExtractionPanel workspacePath={workspacePath} />

      {/* M5c: 工作区批量审校（glob + 规则包 → 汇总 + Markdown 报告）。 */}
      <WordBatchAuditPanel workspacePath={workspacePath ?? ''} />

      <article className="rounded-lg border border-border bg-bg-subtle p-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h3 className="text-sm font-medium text-text">{t('office.rules.guide.title')}</h3>
          <p className="text-xs text-muted mt-1">{t('office.rules.guide.body')}</p>
        </div>
        <button
          type="button"
          onClick={() => setTab('documents')}
          data-testid="office-rules-goto-documents"
          className="shrink-0 px-3 py-1.5 rounded text-sm border border-border text-text-secondary hover:bg-bg-hover"
        >
          {t('office.rules.guide.action')}
        </button>
      </article>
    </div>
  );

  return (
    <div className="flex-1 flex flex-col gap-4 p-6 overflow-y-auto" data-testid="office-page">
      {/* Header */}
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-semibold text-text">{t('office.title')}</h1>
        <OfficeEnvironmentButton workspacePath={workspacePath} onCapabilities={setCapabilities} />
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

      {/* workspaceStatus === 'error' 在顶层始终可见（与 tab 无关），
          新 tab 切换也不会遮盖初始错误。 */}
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
        <Tabs value={activeTab} onValueChange={(value) => setTab(parseOfficeTab(value))}>
          <TabsList aria-label={t('office.tabs.label')} data-testid="office-tabs">
            {OFFICE_TAB_IDS.map((id) => (
              <TabsTrigger key={id} value={id} data-testid={`office-tab-${id}`}>
                {t(TOP_TAB_LABEL_KEYS[id])}
              </TabsTrigger>
            ))}
          </TabsList>
          {OFFICE_TAB_IDS.map((id) => (
            <TabsContent
              key={id}
              value={id}
              forceMount
              hidden={activeTab !== id}
              data-testid={`office-panel-${id}`}
            >
              {mounted.includes(id) &&
                (id === 'documents' ? (
                  renderDocumentsTab()
                ) : id === 'generate' ? (
                  renderGenerateTab()
                ) : id === 'rules' ? (
                  renderRulesTab()
                ) : (
                  <OfficeLatexTab active={activeLatexTab} onChange={setLatexTab} />
                ))}
            </TabsContent>
          ))}
        </Tabs>
      )}

      <OfficeDuplicateDialog pending={pendingDuplicate} onChoose={resolvePendingDuplicate} />

      <WorkspaceBindModal
        isOpen={isBindModalOpen}
        onClose={handleBindModalClose}
        currentPath={workspacePath}
        bind={bind}
        revoke={revoke}
      />

      {workspacePath && (
        <OfficeAiSidebarHost
          activeTab={activeTab as QuickActionTab}
          onNavigateTab={(tab) => setTab(tab as OfficeTabId)}
        />
      )}
    </div>
  );
}

export default Office;

// eslint-disable-next-line react-refresh/only-export-components
export function auditOfficePageGovernance(
  state: {
    activeMode?: 'generate' | 'edit' | 'preview' | string;
    documentFormat?: 'ppt' | 'docx' | 'xlsx' | string;
    isGenerating?: boolean;
  } = {},
): {
  module: 'src/pages/Office.tsx';
  phase: 'P142';
  activeMode: 'generate' | 'edit' | 'preview';
  documentFormat: 'ppt' | 'docx' | 'xlsx';
  isGenerating: boolean;
  healthy: boolean;
} {
  const activeMode =
    state.activeMode === 'edit' || state.activeMode === 'preview' ? state.activeMode : 'generate';
  const documentFormat =
    state.documentFormat === 'docx' || state.documentFormat === 'xlsx'
      ? state.documentFormat
      : 'ppt';
  const isGenerating = Boolean(state.isGenerating);
  return {
    module: 'src/pages/Office.tsx',
    phase: 'P142',
    activeMode,
    documentFormat,
    isGenerating,
    healthy: true,
  };
}
