import { useState } from 'react';

import type {
  OfficeExcelReadResult,
  OfficeExcelSheetContent,
  OfficePdfReadResult,
  OfficePptReadResult,
  OfficeWordReadResult,
} from '../../shared/api/types';
import { renderInlineMarks } from '../../shared/lib/InlineMarks';
import { useI18n } from '../../shared/lib/i18n';
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

export function PdfPreview({ data }: { data: OfficePdfReadResult }) {
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
                {/* P3-A: 显示 id —— 删除批注 op 需要 comment_id */}
                <span className="font-mono text-ui-xs">#{comment.id}</span>
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
