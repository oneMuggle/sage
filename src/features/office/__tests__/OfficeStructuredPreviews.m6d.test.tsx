/**
 * M6d — PPT 图片网格与 Excel/PPT 图表迷你图渲染。
 * 数据契约：PptSlideContent.images/images_omitted、OfficeExcelChart.
 * categories/series_items/truncated（backend/office/models/_shared.py、
 * backend/office/excel.py _extract_sheet_charts）。
 */
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

function renderZh(node: React.ReactElement) {
  return render(<I18nProvider defaultLocale="zh">{node}</I18nProvider>);
}

describe('OfficeStructuredPreviews — M6d 媒体渲染', () => {
  it('renders PPT embedded images and the omitted count', () => {
    const data: OfficePptReadResult = {
      summary: makeSummary('ppt', 'deck.pptx'),
      slides: [
        {
          index: 0,
          title: '架构图',
          text_blocks: [],
          table_count: 0,
          image_count: 3,
          notes: null,
          images: [
            {
              name: '图片 1',
              content_type: 'image/png',
              width_px: 640,
              height_px: 480,
              bytes: 1234,
              data_url: 'data:image/png;base64,AAAA',
            },
          ],
          images_omitted: 2,
        },
      ],
    };
    renderZh(<PptPreview data={data} />);

    const block = screen.getByTestId('office-ppt-images');
    expect(block).toBeTruthy();
    const img = block.querySelector('img');
    expect(img?.getAttribute('src')).toBe('data:image/png;base64,AAAA');
    expect(img?.getAttribute('alt')).toBe('图片 1');
    expect(block.textContent).toContain('另有 2 张图片未内联');
  });

  it('does not render the PPT image block when nothing was enumerated', () => {
    const data: OfficePptReadResult = {
      summary: makeSummary('ppt', 'deck.pptx'),
      slides: [
        {
          index: 0,
          title: '纯文字',
          text_blocks: ['只有文本'],
          table_count: 0,
          image_count: 0,
          notes: null,
          images: [],
          images_omitted: 0,
        },
      ],
    };
    renderZh(<PptPreview data={data} />);
    expect(screen.queryByTestId('office-ppt-images')).toBeNull();
  });

  it('renders a mini chart for PPT series values', () => {
    const data: OfficePptReadResult = {
      summary: makeSummary('ppt', 'deck.pptx'),
      slides: [
        {
          index: 0,
          title: '季度回顾',
          text_blocks: [],
          table_count: 0,
          image_count: 0,
          notes: null,
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
    renderZh(<PptPreview data={data} />);

    const chartBlock = screen.getByTestId('office-ppt-charts');
    expect(chartBlock.querySelector('[data-testid="office-mini-chart"]')).toBeTruthy();
    // 每个非零数值一根柱子：2 系列 × 2 点 = 4
    expect(chartBlock.querySelectorAll('rect').length).toBe(4);
  });

  it('renders Excel chart mini bars from series_items plus the truncation note', () => {
    const data: OfficeExcelReadResult = {
      summary: makeSummary('excel', 'book.xlsx'),
      sheets: [
        {
          name: 'Sheet1',
          rows: [['月份', '销量']],
          max_row: 1,
          max_col: 2,
          charts: [
            {
              type: 'BarChart',
              series: 1,
              title: '月度销量',
              categories: ['1月', '2月'],
              series_items: [{ name: '销量', values: [5, 8] }],
              truncated: true,
            },
          ],
        },
      ],
    };
    renderZh(<ExcelPreview data={data} />);

    const chartBlock = screen.getByTestId('office-excel-charts');
    expect(chartBlock.querySelector('[data-testid="office-mini-chart"]')).toBeTruthy();
    expect(chartBlock.querySelectorAll('rect').length).toBe(2);
    expect(chartBlock.textContent).toContain('数据点已截断');
  });

  it('keeps the text-only chart list when series_items is absent', () => {
    const data: OfficeExcelReadResult = {
      summary: makeSummary('excel', 'book.xlsx'),
      sheets: [
        {
          name: 'Sheet1',
          rows: [['月份', '销量']],
          max_row: 1,
          max_col: 2,
          charts: [{ type: 'BarChart', series: 2, title: '旧缓存图表' }],
        },
      ],
    };
    renderZh(<ExcelPreview data={data} />);

    const chartBlock = screen.getByTestId('office-excel-charts');
    expect(chartBlock.querySelector('[data-testid="office-mini-chart"]')).toBeNull();
    expect(chartBlock.textContent).toContain('旧缓存图表');
    expect(chartBlock.textContent).toContain('series: 2');
  });
});
