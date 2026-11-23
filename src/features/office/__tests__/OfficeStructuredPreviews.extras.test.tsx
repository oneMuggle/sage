import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type {
  OfficeDocType,
  OfficeDocumentSummary,
  OfficeExcelReadResult,
  OfficePptReadResult,
} from '../../../shared/api/types';
import { I18nProvider } from '../../../shared/lib/i18n';
import { ExcelPreview, PptPreview } from '../OfficeStructuredPreviews';

function makeSummary(docType: OfficeDocType, filename: string): OfficeDocumentSummary {
  return {
    id: `doc-${docType}`,
    doc_type: docType,
    original_filename: filename,
    generated_filename: filename,
    status: 'parsed',
    created_at: 0,
    updated_at: 0,
    metadata: { file_size_bytes: 1024 },
    derived_from: null,
    archived_at: null,
  };
}

describe('OfficeStructuredPreviews — M6b read-side extras', () => {
  it('renders PPT layout, placeholders and native charts', () => {
    const data: OfficePptReadResult = {
      summary: makeSummary('ppt', 'deck.pptx'),
      slides: [
        {
          index: 0,
          title: '季度回顾',
          text_blocks: ['营收增长'],
          table_count: 0,
          image_count: 0,
          notes: null,
          layout: 'Title and Content',
          placeholders: [
            { idx: 1, type: 'title', name: 'Title 1', text: '季度回顾' },
            { idx: 2, type: 'body', name: 'Content Placeholder 2', text: null },
          ],
          charts: [
            {
              type: 'barChart',
              categories: ['Q1', 'Q2'],
              series: [
                { name: '营收', values: [10, 20] },
                { name: '成本', values: [4, 8] },
              ],
              truncated: false,
            },
          ],
        },
      ],
    };
    render(
      <I18nProvider defaultLocale="zh">
        <PptPreview data={data} />
      </I18nProvider>,
    );

    expect(screen.getByText('Title and Content')).toBeInTheDocument();
    expect(screen.getByTestId('office-ppt-placeholders')).toHaveTextContent(
      'Content Placeholder 2',
    );
    expect(screen.getByTestId('office-ppt-charts')).toHaveTextContent('barChart');
    expect(screen.getByTestId('office-ppt-charts')).toHaveTextContent('营收, 成本');
  });

  it('renders Excel charts, conditional formats and data validations', () => {
    const data: OfficeExcelReadResult = {
      summary: makeSummary('excel', 'book.xlsx'),
      sheets: [
        {
          name: 'Sheet1',
          rows: [
            ['名称', '金额'],
            ['A', '10'],
          ],
          max_row: 2,
          max_col: 2,
          charts: [{ type: 'bar', series: 2, title: '月度对比' }],
          conditional_formats: [
            {
              range: 'B2:B10',
              rules: [{ type: 'cellIs', operator: 'greaterThan', formula: '100' }],
            },
          ],
          data_validations: [
            {
              type: 'list',
              operator: null,
              formula1: '"是,否"',
              formula2: null,
              sqref: 'C2:C10',
            },
          ],
        },
      ],
    };
    render(
      <I18nProvider defaultLocale="zh">
        <ExcelPreview data={data} />
      </I18nProvider>,
    );

    expect(screen.getByTestId('office-excel-charts')).toHaveTextContent('月度对比');
    expect(screen.getByTestId('office-excel-conditional-formats')).toHaveTextContent('B2:B10');
    expect(screen.getByTestId('office-excel-conditional-formats')).toHaveTextContent('cellIs');
    expect(screen.getByTestId('office-excel-data-validations')).toHaveTextContent('C2:C10');
  });
});
