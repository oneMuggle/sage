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

import { FileDown, FileSpreadsheet, FileText, FileType, Pencil, Presentation } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { officeApi } from '../../shared/api/officeApi';
import type {
  OfficeDocType,
  OfficeExcelReadResult,
  OfficeExcelSheetContent,
  OfficePdfReadResult,
  OfficePptReadResult,
  OfficeWordReadResult,
} from '../../shared/api/types';
import { useI18n } from '../../shared/lib/i18n';

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

export function OfficePreviewPanel({ preview, workspacePath, onEditPreview }: OfficePreviewPanelProps) {
  const { t } = useI18n();
  const [exporting, setExporting] = useState(false);

  if (!preview) {
    return (
      <div className="flex items-center justify-center p-12 text-muted text-sm border border-dashed border-border rounded-lg">
        {t('office.preview.empty')}
      </div>
    );
  }

  const summary = preview.data.summary;

  const handleExportPdf = async () => {
    if (exporting) return;
    const ws = workspacePath ?? summary.workspace_path;
    if (!ws) {
      toast.error(t('office.export.failed'));
      return;
    }
    // Managed layout `<workspace>/office/<docType>/<docId>/<filename>` —
    // the same reconstruction readDocument uses (useOfficeDocuments).
    const managedPath = [
      ws,
      'office',
      summary.doc_type,
      summary.id,
      summary.generated_filename,
    ].join('/');
    setExporting(true);
    try {
      const res = await officeApi.exportPdf({ workspace_path: ws, file_path: managedPath });
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
      setExporting(false);
    }
  };

  return (
    <div className="border border-border rounded-lg bg-surface overflow-hidden" data-testid="office-preview-panel">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-border bg-bg-subtle">
        {preview.docType === 'ppt' && <Presentation className="w-4 h-4" />}
        {preview.docType === 'word' && <FileText className="w-4 h-4" />}
        {preview.docType === 'excel' && <FileSpreadsheet className="w-4 h-4" />}
        {preview.docType === 'pdf' && <FileType className="w-4 h-4" />}
        <span className="font-medium text-sm truncate">{summary.generated_filename}</span>
        <span className="ml-auto text-xs text-muted shrink-0">
          {(summary.metadata.file_size_bytes / 1024).toFixed(1)} KB
        </span>
        {isEditableDocType(preview.docType) && (
          <div className="flex items-center gap-1 shrink-0">
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
              <FileDown className="w-3.5 h-3.5" />
              {exporting ? t('office.export.exporting') : t('office.export.pdf')}
            </button>
          </div>
        )}
      </div>

      <div className="p-4 max-h-96 overflow-y-auto">
        {preview.docType === 'ppt' && <PptPreview data={preview.data} />}
        {preview.docType === 'word' && <WordPreview data={preview.data} />}
        {preview.docType === 'excel' && <ExcelPreview key={summary.id} data={preview.data} />}
        {preview.docType === 'pdf' && <PdfPreview data={preview.data} />}
      </div>
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

function PptPreview({ data }: { data: OfficePptReadResult }) {
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

function PdfPreview({ data }: { data: OfficePdfReadResult }) {
  const { t } = useI18n();
  if (data.pages.length === 0) {
    return <p className="text-muted text-sm">{t('office.preview.emptyPdf')}</p>;
  }
  return (
    <ol className="space-y-3">
      {data.pages.map((page) => (
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
  );
}

function WordPreview({ data }: { data: OfficeWordReadResult }) {
  const { t } = useI18n();
  const shown = data.paragraphs.slice(0, PARAGRAPH_RENDER_CAP);
  const hidden = data.paragraphs.length - shown.length;
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
                <span className="min-w-0">{para.text}</span>
              </div>
            );
          }
          return (
            <p key={i} className="text-sm text-text-secondary leading-relaxed">
              {para.text}
            </p>
          );
        })}
      </div>
      {hidden > 0 && (
        <p className="text-xs text-muted">
          {t('office.preview.paragraphsTruncated').replace('{n}', String(hidden))}
        </p>
      )}
      {data.tables.map((table, i) => (
        <div key={i} className="mt-3">
          <CappedTable rows={table.rows} />
        </div>
      ))}
    </div>
  );
}

function ExcelSheetTable({ sheet }: { sheet: OfficeExcelSheetContent }) {
  const { t } = useI18n();
  const shownRows = sheet.rows.slice(0, ROW_RENDER_CAP);
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
                <span>
                  {t('office.preview.rowsTruncated').replace('{n}', String(hiddenRows))}
                </span>
              )}
              {hiddenRows > 0 && hiddenCols > 0 && <span className="mx-2">·</span>}
              {hiddenCols > 0 && (
                <span>
                  {t('office.preview.cellsTruncated').replace('{n}', String(hiddenCols))}
                </span>
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

function ExcelPreview({ data }: { data: OfficeExcelReadResult }) {
  const { t } = useI18n();
  const [activeSheet, setActiveSheet] = useState(0);
  if (data.sheets.length === 0) {
    return <p className="text-muted text-sm">{t('office.preview.emptyWorkbook')}</p>;
  }
  const sheet = data.sheets[Math.min(activeSheet, data.sheets.length - 1)];
  return (
    <div className="space-y-3">
      {/* Per-sheet tabs (stacked sections don't scale past a few sheets). */}
      <div className="flex items-center gap-1 flex-wrap" role="tablist" data-testid="office-excel-tabs">
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
        <ExcelSheetTable sheet={sheet} />
      </div>
    </div>
  );
}
