/**
 * OfficePreviewPanel — render read results from any Office doc type.
 *
 * Discriminates on the `summary.doc_type` field and renders the appropriate
 * sub-layout (PPT slides / Word paragraphs+tables / Excel sheets / PDF pages).
 *
 * Office parity batch 1 (item 1.2): added the PDF page-card preview.
 *
 * Office parity batch 2 (item 2.6): Word/Excel/PPT now render from the
 * structured read results with real typography —
 *   Word : heading size/weight scale, prose paragraphs, lists preserved,
 *          bordered tables, inline image count.
 *   Excel: per-sheet tabs, styled header row, right-aligned monospace
 *          numerals, sheet dims, formula-view code list (additive
 *          `formulas` field from read_xlsx include_formulas).
 *   PPT  : slide cards with number badge, emphasized title, bullet list,
 *          collapsible notes.
 * Long content is render-capped (ROW/PARAGRAPH/COLUMN caps + a "…还有 N
 * 行" note) and the whole body scrolls — a 10k-row sheet must not
 * produce 10k DOM rows.
 *
 * Office parity batch 2 (item 2.7): the toolbar carries 导出 PDF for
 * word/excel/ppt docs (POST /office/export-pdf → locally installed
 * LibreOffice / MS Word converter). Failures surface via toast; the
 * success toast offers 打开所在文件夹 through the existing managed-file
 * gateway (the exported `<stem>.pdf` sits next to the managed source).
 */

import {
  Eye,
  FileDown,
  FileSpreadsheet,
  FileText,
  FileType,
  Pencil,
  Presentation,
} from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

import { useTaskCenterStore } from '../../features/task-center/taskCenterStore';
import { officeApi } from '../../shared/api/officeApi';
import type {
  OfficeDocType,
  OfficeExcelReadResult,
  OfficePdfReadResult,
  OfficePptReadResult,
  OfficeWordReadResult,
} from '../../shared/api/types';
import { useI18n } from '../../shared/lib/i18n';
import { useElapsedSeconds } from '../../shared/lib/useElapsedSeconds';

import { DocxNativePreview } from './DocxNativePreview';
import {
  ExcelPreview,
  PARAGRAPH_RENDER_CAP,
  PdfPreview,
  PptPreview,
  ROW_RENDER_CAP,
  WordPreview,
} from './OfficeStructuredPreviews';
import { PdfFormFillDialog } from './PdfFormFillDialog';
import { pollOfficeProgress } from './officeProgress';
import { buildPreviewCacheKey, isCurrentKey } from './previewRevision';

export { ExcelPreview, PARAGRAPH_RENDER_CAP, PptPreview, ROW_RENDER_CAP, WordPreview };

export type OfficePreviewData =
  | { docType: 'ppt'; data: OfficePptReadResult }
  | { docType: 'word'; data: OfficeWordReadResult }
  | { docType: 'excel'; data: OfficeExcelReadResult }
  | { docType: 'pdf'; data: OfficePdfReadResult };

export interface OfficePreviewPanelProps {
  preview: OfficePreviewData | null;
  /**
   * Workspace root — preferred over summary.workspace_path when building
   * the managed path for the PDF-export call. Read-result summaries carry
   * workspace_path, but the field is optional on the shared summary type.
   */
  workspacePath?: string;
  /**
   * Item 2.5: opens the edit-preview dialog for the current document.
   * Absent → no 编辑预览 button (e.g. pdf previews).
   */
  onEditPreview?: () => void;
  /**
   * Round A P1: whether the 高保真 toggle is offered at all — wired to
   * the current document format's converter discovery (no converter → no toggle,
   * the badge bar explains why). Defaults to true so existing callers
   * and tests keep the button. Also gates PDF export; Word native preview
   * remains available without a PDF converter.
   */
  fidelityAvailable?: boolean;
  /**
   * P2-C/P2-D (office-p2c/p2d): re-read the current document after an
   * in-place mutation (excel formula-cache recalc / PDF form fill producing
   * a new managed copy). Absent → recalc/form buttons are hidden.
   */
  onRefresh?: () => void;
}

/** Docs that can be exported to PDF (item 2.7) and edited (item 2.5). */
function isEditableDocType(docType: OfficeDocType): boolean {
  return docType === 'word' || docType === 'excel' || docType === 'ppt';
}

export function OfficePreviewPanel({
  preview,
  workspacePath,
  onEditPreview,
  onRefresh,
  fidelityAvailable = true,
}: OfficePreviewPanelProps) {
  const { t } = useI18n();
  const [exporting, setExporting] = useState(false);
  // P2: 导出已耗时（spinner + 秒表，统一按钮 busy 规范）
  const elapsed = useElapsedSeconds(exporting);
  // P16: 可视化进度条（百分比来自任务中心 store 轮询）
  const taskPercent = useTaskCenterStore((s) =>
    exporting ? (s.tasks['office:export']?.percent ?? null) : null,
  );
  // F3 (office-p0): PDF 原文预览 —— data URL + iframe（Chromium 内置
  // viewer）。懒加载：点开关才请求 base64；切文档自动回落结构视图。
  const [originalPdfUrl, setOriginalPdfUrl] = useState<string | null>(null);
  const [loadingOriginal, setLoadingOriginal] = useState(false);
  const summaryId = preview?.data.summary.id;
  useEffect(() => {
    setOriginalPdfUrl(null);
    setLoadingOriginal(false);
  }, [summaryId]);

  // F2 (office-p0-a): content revision of the shown document. Every render
  // cache below keys on it, so a same-size edit can no longer reuse a stale
  // rendering. Re-fetched whenever the row changes (switch, edit, restore);
  // a failed probe degrades the key instead of blocking the preview.
  const summaryUpdatedAt = preview?.data.summary.updated_at;
  const summarySize = preview?.data.summary.metadata.file_size_bytes;
  const [docRevision, setDocRevision] = useState<string | null>(null);
  // Mirrors the cache key of the LATEST render so async results can check
  // whether they are still relevant when they land.
  const currentFidelityKeyRef = useRef<string>('');
  useEffect(() => {
    let cancelled = false;
    setDocRevision(null);
    if (!summaryId) return;
    // Promise.resolve() wrapper: the probe is additive, so a build/test
    // double that lacks docRevision must degrade the cache key, not throw
    // out of the effect.
    void Promise.resolve()
      .then(() => officeApi.docRevision(summaryId))
      .then((res) => {
        if (!cancelled) setDocRevision(res.revision ?? null);
      })
      .catch(() => {
        if (!cancelled) setDocRevision(null);
      });
    return () => {
      cancelled = true;
    };
  }, [summaryId, summaryUpdatedAt, summarySize]);

  // P2-D (office-p2d): PDF AcroForm 表单填写对话框
  const [formDialogOpen, setFormDialogOpen] = useState(false);
  // P2-C (office-p2c): excel 公式缓存重算（soffice 重算回写，重算前服务端自动快照）
  const [recalcing, setRecalcing] = useState(false);
  const handleRecalcExcel = async () => {
    if (recalcing) return;
    const ws = workspacePath ?? summary.workspace_path;
    if (!ws) {
      toast.error(t('office.recalc.failed'));
      return;
    }
    setRecalcing(true);
    try {
      const res = await officeApi.recalcExcel({
        workspace_path: ws,
        file_path: buildManagedPath(ws),
      });
      if (res.ok) {
        toast.success(t('office.recalc.success'));
        onRefresh?.();
      } else {
        toast.error(`${t('office.recalc.failed')}: ${res.error ?? ''}`.trimEnd());
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`${t('office.recalc.failed')}: ${msg}`);
    } finally {
      setRecalcing(false);
    }
  };

  // Round A P1: 高保真视图（docx/xlsx/pptx → 缓存 PDF → 内嵌 viewer）。
  // data URL 以 summary.id + updated_at 为 key 缓存在组件状态里 —— 文档
  // 一变 key 即不同，重开视图会重新拉取（后端另有 mtime 级缓存兜底）。
  const [fidelityOn, setFidelityOn] = useState(false);
  const [fidelityLoading, setFidelityLoading] = useState(false);
  const [fidelityUrl, setFidelityUrl] = useState<string | null>(null);
  const [fidelityKey, setFidelityKey] = useState<string | null>(null);
  const fidelityElapsed = useElapsedSeconds(fidelityLoading);

  if (!preview) {
    return (
      <div className="flex items-center justify-center p-12 text-muted text-sm border border-dashed border-border rounded-lg">
        {t('office.preview.empty')}
      </div>
    );
  }

  const summary = preview.data.summary;
  // F2: content-revision cache identity (falls back to the legacy
  // updated_at/size triple when the revision probe failed).
  const currentFidelityKey = buildPreviewCacheKey({
    docId: summary.id,
    revision: docRevision,
    updatedAt: summary.updated_at,
    sizeBytes: summary.metadata.file_size_bytes,
  }).key;
  currentFidelityKeyRef.current = currentFidelityKey;

  const buildManagedPath = (ws: string) =>
    [ws, 'office', summary.doc_type, summary.id, summary.generated_filename].join('/');

  const handleToggleFidelity = async () => {
    if (fidelityLoading) return;
    if (fidelityOn) {
      setFidelityOn(false);
      return;
    }
    // P2-B: word + 无本机转换器 → 原生渲染模式（不请求 soffice 转换）。
    if (!fidelityAvailable && preview?.docType === 'word') {
      setFidelityOn(true);
      return;
    }
    // Cached data URL for the same doc state → instant toggle.
    if (fidelityUrl && fidelityKey === currentFidelityKey) {
      setFidelityOn(true);
      return;
    }
    const ws = workspacePath ?? summary.workspace_path;
    if (!ws) {
      toast.error(t('office.fidelity.failed'));
      return;
    }
    setFidelityLoading(true);
    try {
      const res = await officeApi.pdfPreview({
        workspace_path: ws,
        file_path: buildManagedPath(ws),
      });
      // Late response: the user may have switched documents or the file may
      // have changed while the converter ran — such a result must not be
      // shown or cached under the current key.
      if (!isCurrentKey(currentFidelityKey, currentFidelityKeyRef.current)) {
        return;
      }
      if (res.ok && res.data_url) {
        setFidelityUrl(res.data_url);
        setFidelityKey(currentFidelityKey);
        setFidelityOn(true);
        return;
      }
      const noConverter = typeof res.error === 'string' && res.error.includes('soffice');
      toast.error(
        noConverter
          ? t('office.export.noConverter')
          : `${t('office.fidelity.failed')}: ${res.error ?? ''}`.trimEnd(),
      );
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`${t('office.fidelity.failed')}: ${msg}`);
    } finally {
      setFidelityLoading(false);
    }
  };

  // F3 (office-p0): pdf 源文件的原文预览（高保真管线仅覆盖 docx/xlsx/pptx
  // 的 office→pdf 转换；pdf 源直接取原始字节，同 20MB 上限口径）。
  const handleToggleOriginalPdf = async () => {
    if (originalPdfUrl) {
      setOriginalPdfUrl(null);
      return;
    }
    const ws = workspacePath ?? summary.workspace_path;
    if (!ws) {
      toast.error(t('office.preview.originalFailed'));
      return;
    }
    const filePath = buildManagedPath(ws);
    setLoadingOriginal(true);
    try {
      const res = await officeApi.readPdfData({
        workspace_path: workspacePath ?? summary.workspace_path ?? '',
        file_path: filePath,
      });
      if (res.ok && res.data_url) {
        setOriginalPdfUrl(res.data_url);
      } else {
        toast.error(`${t('office.preview.originalFailed')}: ${res.error ?? ''}`.trimEnd());
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`${t('office.preview.originalFailed')}: ${msg}`);
    } finally {
      setLoadingOriginal(false);
    }
  };

  const handleExportPdf = async () => {
    if (exporting || !fidelityAvailable) return;
    const ws = workspacePath ?? summary.workspace_path;
    if (!ws) {
      toast.error(t('office.export.failed'));
      return;
    }
    // Managed layout `<workspace>/office/<docType>/<docId>/<filename>` —
    // the same reconstruction readDocument uses (useOfficeDocuments).
    const managedPath = buildManagedPath(ws);
    setExporting(true);
    // P7: 进度追踪任务 id + 轮询（同 OfficeGenerateForm）
    const taskId = crypto.randomUUID();
    const stopPoll = pollOfficeProgress(taskId, (p) =>
      useTaskCenterStore.getState().updateTask('office:export', {
        phase: p.stage ?? undefined,
        percent: p.percent,
      }),
    );
    useTaskCenterStore
      .getState()
      .registerTask('office:export', 'office', '导出 PDF', undefined, summary.generated_filename);
    try {
      const res = await officeApi.exportPdf({
        workspace_path: ws,
        file_path: managedPath,
        task_id: taskId,
      });
      if (res.ok && res.output_path) {
        toast.success(t('office.export.success'), {
          description: res.output_path,
          action: window.electronAPI
            ? {
                label: t('office.export.openFolder'),
                onClick: () => {
                  void window.electronAPI?.office
                    .showOfficeDocumentInFolder({
                      workspacePath: ws,
                      docType: summary.doc_type,
                      documentId: summary.id,
                      filename: summary.generated_filename,
                    })
                    .catch(() => {
                      // Gateway failure is non-fatal here — the export
                      // itself already succeeded.
                    });
                },
              }
            : undefined,
          // Round A 快速修补：第二动作「打开 PDF」直达产物本身（sonner 的
          // cancel 槽渲染为次级按钮）。导出产物 <stem>.pdf 与源文件同目录，
          // 走同一 managed-file 网关校验。
          cancel: window.electronAPI
            ? {
                label: t('office.export.openPdf'),
                onClick: () => {
                  const stem = summary.generated_filename.replace(/\.[^.]+$/, '');
                  void window.electronAPI?.office
                    .openOfficeDocument({
                      workspacePath: ws,
                      docType: summary.doc_type,
                      documentId: summary.id,
                      filename: `${stem}.pdf`,
                    })
                    .catch(() => {
                      // Non-fatal — the export itself already succeeded.
                    });
                },
              }
            : undefined,
        });
        return;
      }
      // ok=false: the backend reports converter problems in `error`.
      // The "no local converter" path is the only one whose message
      // mentions the soffice executable — map it to the dedicated i18n
      // string; everything else keeps the raw backend detail.
      const noConverter = typeof res.error === 'string' && res.error.includes('soffice');
      toast.error(
        noConverter
          ? t('office.export.noConverter')
          : `${t('office.export.failed')}: ${res.error ?? ''}`.trimEnd(),
      );
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`${t('office.export.failed')}: ${msg}`);
    } finally {
      stopPoll();
      useTaskCenterStore.getState().finishTask('office:export');
      setExporting(false);
    }
  };

  return (
    <div
      className="border border-border rounded-lg bg-surface overflow-hidden"
      data-testid="office-preview-panel"
    >
      <div className="flex items-center gap-2 px-4 py-3 border-b border-border bg-bg-subtle">
        {preview.docType === 'ppt' && <Presentation className="w-4 h-4" />}
        {preview.docType === 'word' && <FileText className="w-4 h-4" />}
        {preview.docType === 'excel' && <FileSpreadsheet className="w-4 h-4" />}
        {preview.docType === 'pdf' && <FileType className="w-4 h-4" />}
        <span className="font-medium text-sm truncate">{summary.generated_filename}</span>
        <span className="ml-auto text-xs text-muted shrink-0">
          {(summary.metadata.file_size_bytes / 1024).toFixed(1)} KB
        </span>
        {preview.docType === 'pdf' && (
          <button
            type="button"
            onClick={() => void handleToggleOriginalPdf()}
            disabled={loadingOriginal}
            className="flex items-center gap-1 px-2 py-1 rounded border border-border text-xs text-text-secondary hover:bg-bg-hover transition-colors disabled:opacity-50 shrink-0"
            data-testid="office-pdf-original-toggle"
            aria-label={
              originalPdfUrl ? t('office.preview.structuredView') : t('office.preview.originalView')
            }
          >
            {loadingOriginal ? (
              <span
                className="inline-block w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin"
                aria-hidden
              />
            ) : null}
            {originalPdfUrl ? t('office.preview.structuredView') : t('office.preview.originalView')}
          </button>
        )}
        {preview.docType === 'pdf' && onRefresh && (
          <button
            type="button"
            onClick={() => setFormDialogOpen(true)}
            className="flex items-center gap-1 px-2 py-1 rounded border border-border text-xs text-text-secondary hover:bg-bg-hover transition-colors shrink-0"
            data-testid="office-pdf-form-button"
            aria-label={t('office.form.title')}
          >
            {t('office.form.title')}
          </button>
        )}
        {isEditableDocType(preview.docType) && (
          <div className="flex items-center gap-1 shrink-0">
            {/* P2-B: word 无 soffice 时开关仍可用 —— 走 docx-preview 原生渲染 */}
            {(fidelityAvailable || preview.docType === 'word') && (
              <button
                type="button"
                onClick={() => void handleToggleFidelity()}
                disabled={fidelityLoading}
                className={`flex items-center gap-1 px-2 py-1 rounded border text-xs transition-colors disabled:opacity-50 ${
                  fidelityOn
                    ? 'border-primary text-primary bg-primary/10'
                    : 'border-border text-text-secondary hover:bg-bg-hover'
                }`}
                data-testid="office-fidelity-toggle"
                aria-pressed={fidelityOn}
                aria-label={t('office.fidelity.toggle')}
              >
                {fidelityLoading ? (
                  <>
                    <span
                      className="inline-block w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin"
                      aria-hidden
                    />
                    <span className="tabular-nums">
                      {t('office.fidelity.loading')} · {fidelityElapsed}s
                    </span>
                  </>
                ) : (
                  <>
                    <Eye className="w-3.5 h-3.5" />
                    {t('office.fidelity.toggle')}
                  </>
                )}
              </button>
            )}
            {onEditPreview && (
              <button
                type="button"
                onClick={onEditPreview}
                className="flex items-center gap-1 px-2 py-1 rounded border border-border text-xs text-text-secondary hover:bg-bg-hover transition-colors"
                data-testid="office-edit-preview-button"
                aria-label={t('office.edit.open')}
              >
                <Pencil className="w-3.5 h-3.5" />
                {t('office.edit.open')}
              </button>
            )}
            {preview.docType === 'excel' && onRefresh && (
              <button
                type="button"
                onClick={() => void handleRecalcExcel()}
                disabled={recalcing}
                className="flex items-center gap-1 px-2 py-1 rounded border border-border text-xs text-text-secondary hover:bg-bg-hover transition-colors disabled:opacity-50 shrink-0"
                data-testid="office-excel-recalc-button"
                aria-label={t('office.recalc.button')}
              >
                {recalcing ? t('office.recalc.recalcing') : t('office.recalc.button')}
              </button>
            )}
            <button
              type="button"
              onClick={() => void handleExportPdf()}
              disabled={exporting || !fidelityAvailable}
              title={!fidelityAvailable ? t('office.export.noConverter') : undefined}
              className="flex items-center gap-1 px-2 py-1 rounded border border-border text-xs text-text-secondary hover:bg-bg-hover transition-colors disabled:opacity-50"
              data-testid="office-export-pdf-button"
              aria-label={t('office.export.pdf')}
            >
              {exporting ? (
                <>
                  {/* P2: spinner + 已耗时（统一按钮 busy 规范） */}
                  <span
                    className="inline-block w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin"
                    aria-hidden
                  />
                  <span className="tabular-nums">
                    {t('office.export.exporting')} · {elapsed}s
                  </span>
                </>
              ) : (
                <>
                  <FileDown className="w-3.5 h-3.5" />
                  {t('office.export.pdf')}
                </>
              )}
            </button>
          </div>
        )}
      </div>

      {/* P16: 导出期间的可视化进度条（百分比来自任务中心轮询） */}
      {exporting && taskPercent != null && (
        <div
          className="h-1 rounded-full bg-bg-subtle overflow-hidden"
          data-testid="office-export-progress-bar"
        >
          <div
            className="h-full bg-primary rounded-full transition-[width] duration-500"
            style={{ width: `${taskPercent}%` }}
          />
        </div>
      )}

      {formDialogOpen && preview.docType === 'pdf' && (
        <div className="p-4 border-t border-border">
          <PdfFormFillDialog
            workspacePath={workspacePath ?? summary.workspace_path ?? ''}
            managedPath={buildManagedPath(workspacePath ?? summary.workspace_path ?? '')}
            onFilled={onRefresh}
            onClose={() => setFormDialogOpen(false)}
          />
        </div>
      )}

      {/* Round A P1: 高保真开 → 内嵌 Chromium PDF viewer；关 → 结构化预览。
          F3 (office-p0): pdf 源文件另有原文开关（/pdf/data，高保真管线
          不覆盖 pdf 源）。 */}
      {fidelityOn && fidelityUrl ? (
        <iframe
          src={fidelityUrl}
          title={summary.generated_filename}
          className="w-full h-[32rem] border-0"
          data-testid="office-fidelity-frame"
        />
      ) : fidelityOn && preview.docType === 'word' ? (
        <DocxNativePreview
          workspacePath={workspacePath ?? summary.workspace_path ?? ''}
          managedPath={buildManagedPath(workspacePath ?? summary.workspace_path ?? '')}
          revision={docRevision}
        />
      ) : (
        <div className="p-4 max-h-96 overflow-y-auto">
          {preview.docType === 'pdf' && originalPdfUrl ? (
            <iframe
              src={originalPdfUrl}
              title={summary.generated_filename}
              className="w-full h-96 border border-border rounded bg-white"
              data-testid="office-pdf-original-frame"
            />
          ) : (
            <>
              {preview.docType === 'ppt' && <PptPreview data={preview.data} />}
              {preview.docType === 'word' && <WordPreview data={preview.data} />}
              {preview.docType === 'excel' && <ExcelPreview key={summary.id} data={preview.data} />}
              {preview.docType === 'pdf' && <PdfPreview data={preview.data} />}
            </>
          )}
        </div>
      )}
    </div>
  );
}

