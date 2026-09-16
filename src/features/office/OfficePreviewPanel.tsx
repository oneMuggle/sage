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
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { useTaskCenterStore } from '../../features/task-center/taskCenterStore';
import { officeApi } from '../../shared/api/officeApi';
import type {
  OfficeDocType,
  OfficeExcelReadResult,
  OfficeExcelSheetContent,
  OfficePdfReadResult,
  OfficePptReadResult,
  OfficeWordReadResult,
} from '../../shared/api/types';
import { renderInlineMarks } from '../../shared/lib/InlineMarks';
import { useI18n } from '../../shared/lib/i18n';
import { useElapsedSeconds } from '../../shared/lib/useElapsedSeconds';

import { pollOfficeProgress } from './officeProgress';

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
   * capabilities.pdf_export_available (no local converter → no toggle,
   * the badge bar explains why). Defaults to true so existing callers
   * and tests keep the button.
   */
  fidelityAvailable?: boolean;
}

// ──────────────────────────────────────────────────────────────────────
// Render caps (item 2.6): keep the DOM bounded for huge documents. The
// note under each capped block tells the user how much was hidden.
// ──────────────────────────────────────────────────────────────────────

export const ROW_RENDER_CAP = 300;
export const PARAGRAPH_RENDER_CAP = 300;
export const COLUMN_RENDER_CAP = 40;

// Static lookup so Tailwind JIT sees full literal class names at build time
// (don't interpolate text-${level} — Tailwind scans source for literal
// tokens only).
const HEADING_CLASSES: Record<number, string> = {
  1: 'text-xl font-bold text-text',
  2: 'text-lg font-semibold text-text',
  3: 'text-base font-semibold text-text',
};

function headingClass(level: number): string {
  return HEADING_CLASSES[level] ?? 'text-sm font-semibold text-text';
}

/** Excel-style numeric detection — numbers render right-aligned monospace. */
function isNumericCell(cell: string): boolean {
  return cell.trim() !== '' && Number.isFinite(Number(cell));
}

/** Docs that can be exported to PDF (item 2.7) and edited (item 2.5). */
function isEditableDocType(docType: OfficeDocType): boolean {
  return docType === 'word' || docType === 'excel' || docType === 'ppt';
}

export function OfficePreviewPanel({
  preview,
  workspacePath,
  onEditPreview,
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
  const currentFidelityKey = `${summary.id}:${summary.metadata.file_size_bytes}`;

  const buildManagedPath = (ws: string) =>
    [ws, 'office', summary.doc_type, summary.id, summary.generated_filename].join('/');

  const handleToggleFidelity = async () => {
    if (fidelityLoading) return;
    if (fidelityOn) {
      setFidelityOn(false);
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
    if (exporting) return;
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
        {isEditableDocType(preview.docType) && (
          <div className="flex items-center gap-1 shrink-0">
            {fidelityAvailable && (
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
            <button
              type="button"
              onClick={() => void handleExportPdf()}
              disabled={exporting}
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

// ──────────────────────────────────────────────────────────────────────
// Shared table renderer (word + excel + pdf pages): first row is the
// styled header; cells capped; numerals right-aligned monospace.
// ──────────────────────────────────────────────────────────────────────

function CappedTable({ rows, numericCells = false }: { rows: string[][]; numericCells?: boolean }) {
  const { t } = useI18n();
  const [header, ...body] = rows;
  const shownBody = body.slice(0, ROW_RENDER_CAP);
  const hidden = body.length - shownBody.length;
  return (
    <div className="border border-border rounded overflow-x-auto">
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="bg-bg-subtle">
            {header.map((cell, ci) => (
              <th
                key={ci}
                className={`px-3 py-2 border-b border-border text-left font-medium text-text whitespace-nowrap ${
                  numericCells && isNumericCell(cell) ? 'text-right font-mono' : ''
                }`}
              >
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shownBody.map((row, ri) => (
            <tr key={ri} className="even:bg-bg-subtle/40">
              {row.map((cell, ci) => (
                <td
                  key={ci}
                  className={`px-3 py-1.5 border-b border-border last:border-b-0 text-text-secondary ${
                    numericCells && isNumericCell(cell) ? 'text-right font-mono' : ''
                  }`}
                >
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {hidden > 0 && (
        <div className="px-3 py-1.5 text-xs text-muted bg-bg-subtle">
          {t('office.preview.rowsTruncated').replace('{n}', String(hidden))}
        </div>
      )}
    </div>
  );
}

// Round B P3: PptPreview/WordPreview/ExcelPreview are exported — the chat
// ArtifactViewer renders the same structured previews from the artifact
// content's `structured` payload (formula view / header styling / render
// caps all inherited). PdfPreview stays private (chat PDFs use data_url).
export function PptPreview({ data }: { data: OfficePptReadResult }) {
  const { t } = useI18n();
  if (data.slides.length === 0) {
    return <p className="text-muted text-sm">{t('office.preview.emptyPresentation')}</p>;
  }
  return (
    <ol className="space-y-3">
      {data.slides.map((slide) => (
        <li key={slide.index} className="border border-border rounded-lg p-3 bg-surface">
          <div className="flex items-center gap-2 mb-1">
            <span className="inline-flex items-center justify-center min-w-6 h-6 px-1.5 rounded bg-primary/10 text-primary text-xs font-semibold">
              {slide.index + 1}
            </span>
            {slide.title ? (
              <div className="font-semibold text-text text-base truncate">{slide.title}</div>
            ) : (
              <div className="text-sm text-muted italic">
                {t('office.preview.slidePrefix')}
                {slide.index + 1}
                {t('office.preview.slideSuffix')}
              </div>
            )}
          </div>
          {slide.text_blocks.length > 0 && (
            <ul className="text-sm space-y-1 list-disc list-inside text-text-secondary mt-1">
              {slide.text_blocks.map((block, i) => (
                <li key={i}>{block}</li>
              ))}
            </ul>
          )}
          {(slide.table_count > 0 || slide.image_count > 0) && (
            <div className="text-xs text-muted mt-2">
              {slide.table_count > 0 && `${slide.table_count} ${t('office.preview.tableCount')} `}
              {slide.image_count > 0 && `${slide.image_count} ${t('office.preview.imageCount')}`}
            </div>
          )}
          {slide.notes && (
            <details className="mt-2 group">
              <summary className="text-xs text-muted cursor-pointer select-none hover:text-text-secondary">
                {t('office.preview.notes')}
              </summary>
              <p className="text-xs text-muted italic mt-1 whitespace-pre-wrap">{slide.notes}</p>
            </details>
          )}
        </li>
      ))}
    </ol>
  );
}

// P1-A: PDF 页渐进渲染窗口（对齐 Round C P7 的 word/excel 模式 ——
// 数据后端本就全量在手，渲染窗口只管 DOM 规模）。
const PDF_PAGE_WINDOW = 20;

function PdfPreview({ data }: { data: OfficePdfReadResult }) {
  const { t } = useI18n();
  const [pageCap, setPageCap] = useState(PDF_PAGE_WINDOW);
  if (data.pages.length === 0) {
    return <p className="text-muted text-sm">{t('office.preview.emptyPdf')}</p>;
  }
  const shownPages = data.pages.slice(0, pageCap);
  const hiddenPages = data.pages.length - shownPages.length;
  return (
    <div className="space-y-3">
      <ol className="space-y-3">
        {shownPages.map((page) => (
          <li key={page.page_number} className="border border-border rounded-lg p-3 bg-surface">
            <div className="text-xs text-muted mb-1">
              {t('office.preview.pagePrefix')}
              {page.page_number}
              {t('office.preview.pageSuffix')}
            </div>
            {page.text ? (
              <pre className="text-sm text-text-secondary whitespace-pre-wrap font-sans leading-relaxed">
                {page.text}
              </pre>
            ) : (
              <p className="text-xs text-muted italic">{t('office.preview.emptyPage')}</p>
            )}
            {page.tables.length > 0 && (
              <div className="mt-2 space-y-2">
                {page.tables.map((rows, ti) => (
                  <CappedTable key={ti} rows={rows} />
                ))}
              </div>
            )}
          </li>
        ))}
      </ol>
      {hiddenPages > 0 && (
        <button
          type="button"
          onClick={() => setPageCap((c) => c + PDF_PAGE_WINDOW)}
          className="w-full px-3 py-2 rounded border border-border text-xs text-text-secondary hover:bg-bg-hover transition-colors"
          data-testid="office-pdf-load-more"
        >
          {t('office.preview.loadMorePages').replace('{n}', String(hiddenPages))}
        </button>
      )}
    </div>
  );
}

export function WordPreview({ data }: { data: OfficeWordReadResult }) {
  const { t } = useI18n();
  // Round C P7: read results already carry the FULL document (the backend
  // never truncates) — the old hard slice was purely a render guard. 加载
  // 更多 grows the render window instead of hiding the tail forever.
  const [renderCap, setRenderCap] = useState(PARAGRAPH_RENDER_CAP);
  const shown = data.paragraphs.slice(0, renderCap);
  const hidden = data.paragraphs.length - shown.length;
  const headersFooters = data.headers_footers ?? [];
  const tocFields = data.toc_fields ?? [];
  return (
    <div className="space-y-2">
      <p className="text-xs text-muted">
        {data.paragraphs.length} {t('office.preview.paragraphCount')} · {data.tables.length}{' '}
        {t('office.preview.tableCount')} · {data.images} {t('office.preview.imageCount')}
      </p>
      <div className="space-y-1.5">
        {shown.map((para, i) => {
          if (para.level > 0) {
            return (
              <div key={i} className={`mt-3 ${headingClass(para.level)}`}>
                {para.text}
              </div>
            );
          }
          // List styles survive the read as 'List Paragraph' / 'List Bullet'…
          const isListItem = /list/i.test(para.style);
          if (isListItem) {
            return (
              <div key={i} className="flex items-start gap-2 text-sm text-text-secondary">
                <span className="mt-[7px] w-1 h-1 rounded-full bg-current shrink-0" aria-hidden />
                <span className="min-w-0">{renderInlineMarks(para.text)}</span>
              </div>
            );
          }
          return (
            <p key={i} className="text-sm text-text-secondary leading-relaxed">
              {renderInlineMarks(para.text)}
            </p>
          );
        })}
      </div>
      {hidden > 0 && (
        <div className="flex items-center gap-3">
          <p className="text-xs text-muted">
            {t('office.preview.paragraphsTruncated').replace('{n}', String(hidden))}
          </p>
          <button
            type="button"
            onClick={() => setRenderCap((c) => c + PARAGRAPH_RENDER_CAP)}
            className="text-xs text-primary hover:underline"
            data-testid="office-word-load-more"
          >
            {t('office.preview.loadMore')}
          </button>
        </div>
      )}
      {data.tables.map((table, i) => (
        <div key={i} className="mt-3">
          <CappedTable rows={table.rows} />
        </div>
      ))}
      {/* Round C P4: 内嵌图片缩略网格。后端限量（≤10 张、有界 data URL），
          images 总数与 previews 数之差 = 被省略的图片。 */}
      {(data.image_previews?.length ?? 0) > 0 && (
        <div className="mt-3" data-testid="office-word-images">
          <div className="text-xs text-muted mb-1.5">{t('office.preview.imagesTitle')}</div>
          <div className="flex flex-wrap gap-2">
            {data.image_previews!.map((img) => (
              <img
                key={img.index}
                src={img.data_url}
                alt={`image ${img.index + 1}`}
                loading="lazy"
                className="h-24 w-auto max-w-[12rem] object-contain rounded border border-border bg-white"
              />
            ))}
          </div>
          {data.images > data.image_previews!.length && (
            <p className="text-xs text-muted mt-1">
              {t('office.preview.imagesOmitted').replace(
                '{n}',
                String(data.images - data.image_previews!.length),
              )}
            </p>
          )}
        </div>
      )}
      {/* Round C P4: 批注气泡（作者/时间/锚文本 + 正文）。read_docx 早已
          返回 comments，此前预览侧一直未呈现。 */}
      {(data.comments?.length ?? 0) > 0 && (
        <div className="mt-3 space-y-2" data-testid="office-word-comments">
          <div className="text-xs text-muted">
            {t('office.preview.commentsTitle')} ({data.comments!.length})
          </div>
          {data.comments!.map((comment) => (
            <div
              key={comment.id}
              className="border-l-2 border-warning bg-warning/5 rounded-r px-3 py-2 text-xs space-y-1"
            >
              <div className="flex items-center gap-2 text-muted">
                <span className="font-medium text-text-secondary">
                  {comment.author ?? t('office.preview.commentAnonymous')}
                </span>
                {comment.date && <span>{new Date(comment.date).toLocaleString()}</span>}
              </div>
              {comment.anchor_text && (
                <div className="text-muted italic break-all">“{comment.anchor_text}”</div>
              )}
              <div className="text-text-secondary whitespace-pre-wrap break-words">
                {comment.text}
              </div>
            </div>
          ))}
        </div>
      )}
      {headersFooters.length > 0 && (
        <div
          className="mt-3 border border-border rounded bg-bg-subtle/60 p-2"
          data-testid="office-word-headers-footers"
        >
          <div className="text-xs text-muted mb-1">{t('office.preview.headersFooters')}</div>
          <ul className="space-y-1">
            {headersFooters.map((hf) => (
              <li key={hf.section} className="text-xs text-text-secondary">
                <span className="text-muted">S{hf.section}</span> {t('office.preview.headerLabel')}
                {hf.header_text || t('office.preview.emptyLabel')} ·{' '}
                {t('office.preview.footerLabel')}
                {hf.footer_text || t('office.preview.emptyLabel')}
                {hf.has_page_number_field && (
                  <span className="ml-1 text-primary">· {t('office.preview.pageNumberField')}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      {tocFields.length > 0 && (
        <details
          className="mt-3 border border-border rounded bg-bg-subtle/60 p-2"
          data-testid="office-word-toc"
        >
          <summary className="text-xs text-muted cursor-pointer select-none hover:text-text-secondary">
            {t('office.preview.tocFields')}（{tocFields.length}）
          </summary>
          <ul className="mt-1 space-y-0.5">
            {tocFields.map((instr, i) => (
              <li key={i} className="font-mono text-xs text-text-secondary break-all">
                {instr}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function ExcelSheetTable({ sheet }: { sheet: OfficeExcelSheetContent }) {
  const { t } = useI18n();
  // Round C P7: render-window paging（同 WordPreview——数据已全量在手，
  // 只放宽渲染窗口）。sheet 切换时由 ExcelPreview 的 key 重置。
  const [rowCap, setRowCap] = useState(ROW_RENDER_CAP);
  const shownRows = sheet.rows.slice(0, rowCap);
  const hiddenRows = sheet.rows.length - shownRows.length;
  const shownCols = COLUMN_RENDER_CAP;
  const clippedRows = shownRows.map((row) => {
    if (row.length <= shownCols) return row;
    return row.slice(0, shownCols);
  });
  const hiddenCols = sheet.max_col > shownCols ? sheet.max_col - shownCols : 0;
  return (
    <div className="space-y-2">
      {clippedRows.length === 0 ? (
        <p className="text-xs text-muted">{t('office.preview.emptySheet')}</p>
      ) : (
        <div className="border border-border rounded overflow-x-auto">
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="bg-bg-subtle">
                {clippedRows[0].map((cell, ci) => (
                  <th
                    key={ci}
                    className={`px-3 py-2 border-b border-border text-left font-medium text-text whitespace-nowrap ${
                      isNumericCell(cell) ? 'text-right font-mono' : ''
                    }`}
                  >
                    {cell}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {clippedRows.slice(1).map((row, ri) => (
                <tr key={ri} className="even:bg-bg-subtle/40">
                  {row.map((cell, ci) => (
                    <td
                      key={ci}
                      className={`px-3 py-1.5 border-b border-border last:border-b-0 text-text-secondary ${
                        isNumericCell(cell) ? 'text-right font-mono' : ''
                      }`}
                    >
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {(hiddenRows > 0 || hiddenCols > 0) && (
            <div className="px-3 py-1.5 text-xs text-muted bg-bg-subtle">
              {hiddenRows > 0 && (
                <span>{t('office.preview.rowsTruncated').replace('{n}', String(hiddenRows))}</span>
              )}
              {hiddenRows > 0 && hiddenCols > 0 && <span className="mx-2">·</span>}
              {hiddenCols > 0 && (
                <span>{t('office.preview.cellsTruncated').replace('{n}', String(hiddenCols))}</span>
              )}
              {hiddenRows > 0 && (
                <button
                  type="button"
                  onClick={() => setRowCap((c) => c + ROW_RENDER_CAP)}
                  className="ml-3 text-primary hover:underline"
                  data-testid="office-excel-load-more"
                >
                  {t('office.preview.loadMore')}
                </button>
              )}
            </div>
          )}
        </div>
      )}
      {/* 公式视图 (item 1.4 additive field): render as a subtle code list. */}
      {sheet.formulas && sheet.formulas.length > 0 && (
        <div className="border border-border rounded bg-bg-subtle/60 p-2">
          <div className="text-xs text-muted mb-1">{t('office.preview.formulas')}</div>
          <ul className="space-y-0.5">
            {sheet.formulas.slice(0, ROW_RENDER_CAP).map((entry, i) => (
              <li key={i} className="font-mono text-xs text-text-secondary break-all">
                {entry}
              </li>
            ))}
          </ul>
          {sheet.note && (
            <p className="text-xs text-muted italic mt-1">{t('office.preview.formulasNote')}</p>
          )}
        </div>
      )}
    </div>
  );
}

export function ExcelPreview({ data }: { data: OfficeExcelReadResult }) {
  const { t } = useI18n();
  const [activeSheet, setActiveSheet] = useState(0);
  if (data.sheets.length === 0) {
    return <p className="text-muted text-sm">{t('office.preview.emptyWorkbook')}</p>;
  }
  const sheet = data.sheets[Math.min(activeSheet, data.sheets.length - 1)];
  return (
    <div className="space-y-3">
      {/* Per-sheet tabs (stacked sections don't scale past a few sheets). */}
      <div
        className="flex items-center gap-1 flex-wrap"
        role="tablist"
        data-testid="office-excel-tabs"
      >
        {data.sheets.map((s, i) => (
          <button
            key={s.name}
            type="button"
            role="tab"
            aria-selected={i === activeSheet}
            onClick={() => setActiveSheet(i)}
            className={[
              'px-2.5 py-1 rounded text-xs border transition-colors',
              i === activeSheet
                ? 'border-primary bg-primary/10 text-primary font-medium'
                : 'border-border text-text-secondary hover:bg-bg-hover',
            ].join(' ')}
          >
            {s.name}
          </button>
        ))}
      </div>
      <div>
        <h3 className="text-sm font-semibold text-text mb-2">
          {sheet.name}{' '}
          <span className="text-xs font-normal text-muted">
            ({sheet.max_row} {t('office.preview.rowUnit')} × {sheet.max_col}{' '}
            {t('office.preview.colUnit')})
          </span>
        </h3>
        {/* key 保证切换 sheet 时重置 P7 渲染窗口 */}
        <ExcelSheetTable key={sheet.name} sheet={sheet} />
      </div>
    </div>
  );
}
