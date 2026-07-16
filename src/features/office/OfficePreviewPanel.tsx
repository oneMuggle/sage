/**
 * OfficePreviewPanel — render read results from any Office doc type (Phase 1.3, step 16).
 *
 * Discriminates on the `summary.doc_type` field and renders the appropriate
 * sub-layout (PPT slides / Word paragraphs+tables / Excel sheets).
 */

import { FileSpreadsheet, FileText, Presentation } from 'lucide-react';

import type {
  OfficeExcelReadResult,
  OfficePptReadResult,
  OfficeWordReadResult,
} from '../../shared/api/types';

export type OfficePreviewData =
  | { docType: 'ppt'; data: OfficePptReadResult }
  | { docType: 'word'; data: OfficeWordReadResult }
  | { docType: 'excel'; data: OfficeExcelReadResult };

export interface OfficePreviewPanelProps {
  preview: OfficePreviewData | null;
}

export function OfficePreviewPanel({ preview }: OfficePreviewPanelProps) {
  if (!preview) {
    return (
      <div className="flex items-center justify-center p-12 text-muted text-sm border border-dashed border-border rounded-lg">
        选择一个文件以预览
      </div>
    );
  }

  return (
    <div className="border border-border rounded-lg bg-surface overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-border bg-bg-subtle">
        {preview.docType === 'ppt' && <Presentation className="w-4 h-4" />}
        {preview.docType === 'word' && <FileText className="w-4 h-4" />}
        {preview.docType === 'excel' && <FileSpreadsheet className="w-4 h-4" />}
        <span className="font-medium text-sm">
          {preview.data.summary.generated_filename}
        </span>
        <span className="ml-auto text-xs text-muted">
          {(preview.data.summary.metadata.file_size_bytes / 1024).toFixed(1)} KB
        </span>
      </div>

      <div className="p-4 max-h-96 overflow-y-auto">
        {preview.docType === 'ppt' && <PptPreview data={preview.data} />}
        {preview.docType === 'word' && <WordPreview data={preview.data} />}
        {preview.docType === 'excel' && <ExcelPreview data={preview.data} />}
      </div>
    </div>
  );
}

function PptPreview({ data }: { data: OfficePptReadResult }) {
  if (data.slides.length === 0) {
    return <p className="text-muted text-sm">空演示文稿(0 张幻灯片)</p>;
  }
  return (
    <ol className="space-y-3">
      {data.slides.map((slide) => (
        <li
          key={slide.index}
          className="border border-border rounded p-3"
        >
          <div className="text-xs text-muted mb-1">第 {slide.index + 1} 页</div>
          {slide.title && (
            <div className="font-semibold text-text mb-1">{slide.title}</div>
          )}
          {slide.text_blocks.length > 0 && (
            <ul className="text-sm space-y-0.5 list-disc list-inside text-text-secondary">
              {slide.text_blocks.map((block, i) => (
                <li key={i}>{block}</li>
              ))}
            </ul>
          )}
          {(slide.table_count > 0 || slide.image_count > 0) && (
            <div className="text-xs text-muted mt-2">
              {slide.table_count > 0 && `${slide.table_count} 个表格 `}
              {slide.image_count > 0 && `${slide.image_count} 个图片`}
            </div>
          )}
          {slide.notes && (
            <div className="text-xs text-muted mt-2 italic">
              备注: {slide.notes}
            </div>
          )}
        </li>
      ))}
    </ol>
  );
}

function WordPreview({ data }: { data: OfficeWordReadResult }) {
  return (
    <div className="space-y-2">
      <p className="text-xs text-muted">
        {data.paragraphs.length} 个段落 · {data.tables.length} 个表格 · {data.images} 个图片
      </p>
      {data.paragraphs.map((para, i) => (
        <div
          key={i}
          className={[
            'text-sm',
            para.level > 0
              ? `font-semibold text-text pl-${Math.min(para.level * 2, 6)}`
              : 'text-text-secondary',
          ].join(' ')}
        >
          {para.text}
        </div>
      ))}
      {data.tables.map((table, i) => (
        <div key={i} className="border border-border rounded overflow-x-auto mt-3">
          <table className="w-full text-xs">
            <tbody>
              {table.rows.map((row, ri) => (
                <tr
                  key={ri}
                  className={ri === 0 ? 'bg-bg-subtle font-medium' : ''}
                >
                  {row.map((cell, ci) => (
                    <td
                      key={ci}
                      className="px-3 py-2 border-b border-border last:border-b-0"
                    >
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}

function ExcelPreview({ data }: { data: OfficeExcelReadResult }) {
  if (data.sheets.length === 0) {
    return <p className="text-muted text-sm">空工作簿</p>;
  }
  return (
    <div className="space-y-4">
      {data.sheets.map((sheet) => (
        <div key={sheet.name}>
          <h3 className="text-sm font-semibold text-text mb-2">
            {sheet.name}{' '}
            <span className="text-xs font-normal text-muted">
              ({sheet.max_row} 行 × {sheet.max_col} 列)
            </span>
          </h3>
          {sheet.rows.length === 0 ? (
            <p className="text-xs text-muted">空 sheet</p>
          ) : (
            <div className="border border-border rounded overflow-x-auto">
              <table className="w-full text-xs">
                <tbody>
                  {sheet.rows.map((row, ri) => (
                    <tr
                      key={ri}
                      className={ri === 0 ? 'bg-bg-subtle font-medium' : ''}
                    >
                      {row.map((cell, ci) => (
                        <td
                          key={ci}
                          className="px-3 py-2 border-b border-border last:border-b-0"
                        >
                          {cell}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}