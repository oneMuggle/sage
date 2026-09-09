/**
 * OfficePreviewPanel tests — office parity batch 2.
 *
 * Coverage:
 *  - item 2.6 rich rendering: Word heading scale + tables + image count,
 *    Excel per-sheet tabs + numeric alignment + formula view + row cap,
 *    PPT slide cards + collapsible notes, PDF page cards.
 *  - item 2.7 export button: renders for word/excel/ppt only; success
 *    path toasts with the output path; the "no local converter" failure
 *    (backend error mentioning soffice) maps to the dedicated i18n
 *    message; other failures keep the backend detail.
 *  - empty state preserved from batch 1.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { toast } from 'sonner';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockExportPdf = vi.fn();
vi.mock('../../../shared/api/officeApi', () => ({
  officeApi: {
    exportPdf: (...args: unknown[]) => mockExportPdf(...args),
  },
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import type {
  OfficeExcelReadResult,
  OfficePdfReadResult,
  OfficePptReadResult,
} from '../../../shared/api/types';
import { I18nProvider } from '../../../shared/lib/i18n';
import { OfficePreviewPanel, PARAGRAPH_RENDER_CAP, ROW_RENDER_CAP, type OfficePreviewData } from '../OfficePreviewPanel';

const toastMock = toast as unknown as {
  success: ReturnType<typeof vi.fn>;
  error: ReturnType<typeof vi.fn>;
};

const WORD_SUMMARY = {
  id: 'doc-word',
  workspace_path: '/tmp/ws',
  doc_type: 'word' as const,
  original_filename: null,
  generated_filename: 'report.docx',
  status: 'parsed' as const,
  created_at: 1700000000,
  updated_at: 1700000000,
  metadata: { file_size_bytes: 2048 },
  derived_from: null,
  archived_at: null,
};

const WORD_PREVIEW: OfficePreviewData = {
  docType: 'word',
  data: {
    summary: WORD_SUMMARY,
    paragraphs: [
      { style: 'Heading 1', text: '第一章', level: 1 },
      { style: 'Heading 2', text: '第一节', level: 2 },
      { style: 'Normal', text: '正文段落。', level: 0 },
      { style: 'List Paragraph', text: '列表项一', level: 0 },
    ],
    tables: [{ rows: [['名称', '数量'], ['苹果', '3'], ['香蕉', '12']] }],
    images: 2,
  },
};

const EXCEL_PREVIEW: OfficePreviewData = {
  docType: 'excel',
  data: {
    summary: { ...WORD_SUMMARY, id: 'doc-excel', doc_type: 'excel', generated_filename: 'data.xlsx' },
    sheets: [
      {
        name: 'Sheet1',
        rows: [
          ['名称', '数量'],
          ['苹果', '3'],
          ['香蕉', '12'],
        ],
        max_row: 3,
        max_col: 2,
        formulas: ['B4=SUM(B2:B3) → 15'],
        note: 'cache missing',
      },
      {
        name: 'Sheet2',
        rows: [
          ['年份', '篇数'],
          ['2025', '9'],
        ],
        max_row: 2,
        max_col: 2,
      },
    ],
  } satisfies OfficeExcelReadResult,
};

const PPT_PREVIEW: OfficePreviewData = {
  docType: 'ppt',
  data: {
    summary: { ...WORD_SUMMARY, id: 'doc-ppt', doc_type: 'ppt', generated_filename: 'deck.pptx' },
    slides: [
      {
        index: 0,
        title: '封面',
        text_blocks: ['第一点', '第二点'],
        table_count: 0,
        image_count: 1,
        notes: '演讲备注内容',
      },
    ],
  } satisfies OfficePptReadResult,
};

const PDF_PREVIEW: OfficePreviewData = {
  docType: 'pdf',
  data: {
    summary: { ...WORD_SUMMARY, id: 'doc-pdf', doc_type: 'pdf', generated_filename: 'scan.pdf' },
    pages: [{ page_number: 1, text: '页面文本', tables: [], images: [] }],
    metadata: {},
  } satisfies OfficePdfReadResult,
};

function renderPanel(preview: OfficePreviewData | null, onEditPreview?: () => void) {
  return render(
    <I18nProvider defaultLocale="zh">
      <OfficePreviewPanel preview={preview} workspacePath="/tmp/ws" onEditPreview={onEditPreview} />
    </I18nProvider>,
  );
}

describe('OfficePreviewPanel — rich rendering (item 2.6)', () => {
  beforeEach(() => {
    mockExportPdf.mockReset();
    toastMock.success.mockReset();
    toastMock.error.mockReset();
  });

  it('renders the empty state when no preview is set', () => {
    render(
      <I18nProvider defaultLocale="zh">
        <OfficePreviewPanel preview={null} />
      </I18nProvider>,
    );
    expect(screen.getByText('选择一个文件以预览')).toBeInTheDocument();
  });

  it('renders Word headings, prose, list items, table header and image count', () => {
    renderPanel(WORD_PREVIEW);
    // Image count summary line survives.
    expect(screen.getByText(/2 个图片/)).toBeInTheDocument();
    // Heading text is present (level styling is class-based).
    expect(screen.getByText('第一章')).toBeInTheDocument();
    expect(screen.getByText('第一章').className).toContain('text-xl');
    expect(screen.getByText('第一节').className).toContain('text-lg');
    // Prose paragraph.
    expect(screen.getByText('正文段落。')).toBeInTheDocument();
    // Table renders with the first row as header.
    expect(screen.getByText('名称')).toBeInTheDocument();
    expect(screen.getByText('苹果')).toBeInTheDocument();
  });

  it('caps Word paragraphs at PARAGRAPH_RENDER_CAP with a hidden-count note', () => {
    const paragraphs = Array.from({ length: PARAGRAPH_RENDER_CAP + 5 }, (_, i) => ({
      style: 'Normal',
      text: `段落 ${i}`,
      level: 0,
    }));
    renderPanel({
      docType: 'word',
      data: { ...WORD_PREVIEW.data, paragraphs },
    });
    expect(screen.getByText(/还有 5 段未显示/)).toBeInTheDocument();
  });

  it('renders Excel as per-sheet tabs and switches sheets on click', () => {
    renderPanel(EXCEL_PREVIEW);
    // Default tab shows Sheet1 content.
    expect(screen.getByText('苹果')).toBeInTheDocument();
    // Sheet dims are shown.
    expect(screen.getByText(/3 行 × 2 列/)).toBeInTheDocument();
    // Switch to Sheet2.
    fireEvent.click(screen.getByRole('tab', { name: 'Sheet2' }));
    expect(screen.getByText('年份')).toBeInTheDocument();
    expect(screen.queryByText('苹果')).toBeNull();
  });

  it('right-aligns numeric Excel cells and renders the formula view', () => {
    renderPanel(EXCEL_PREVIEW);
    const numeric = screen.getByText('3');
    expect(numeric.className).toContain('text-right');
    expect(numeric.className).toContain('font-mono');
    // Formula view (additive `formulas` field) renders as a code list.
    expect(screen.getByText('公式视图')).toBeInTheDocument();
    expect(screen.getByText('B4=SUM(B2:B3) → 15')).toBeInTheDocument();
  });

  it('caps Excel rows at ROW_RENDER_CAP with a hidden-rows note', () => {
    const rows = [['表头'], ...Array.from({ length: ROW_RENDER_CAP + 7 }, (_, i) => [`r${i}`])];
    renderPanel({
      docType: 'excel',
      data: {
        summary: EXCEL_PREVIEW.data.summary,
        sheets: [{ name: 'Big', rows, max_row: rows.length, max_col: 1 }],
      },
    });
    // The cap covers the header row as well: 308 total − 300 shown = 8 hidden.
    expect(screen.getByText(/还有 8 行未显示/)).toBeInTheDocument();
  });

  it('renders PPT slide cards with number badge and collapsible notes', () => {
    renderPanel(PPT_PREVIEW);
    expect(screen.getByText('封面')).toBeInTheDocument();
    expect(screen.getByText('第一点')).toBeInTheDocument();
    // Notes are inside a collapsed <details>.
    const details = screen.getByText('演讲备注内容').closest('details');
    expect(details).not.toBeNull();
  });

  it('keeps the PDF page cards', () => {
    renderPanel(PDF_PREVIEW);
    expect(screen.getByText('页面文本')).toBeInTheDocument();
    expect(screen.getByText(/第\s*1\s*页/)).toBeInTheDocument();
  });
});

describe('OfficePreviewPanel — export PDF button (item 2.7)', () => {
  beforeEach(() => {
    mockExportPdf.mockReset();
    toastMock.success.mockReset();
    toastMock.error.mockReset();
  });

  it('hides the export and edit buttons for pdf previews', () => {
    renderPanel(PDF_PREVIEW);
    expect(screen.queryByTestId('office-export-pdf-button')).toBeNull();
    expect(screen.queryByTestId('office-edit-preview-button')).toBeNull();
  });

  it('exports via the managed path and toasts the output path on success', async () => {
    mockExportPdf.mockResolvedValueOnce({
      ok: true,
      method: 'libreoffice',
      output_path: '/tmp/ws/office/word/doc-word/report.pdf',
      error: null,
    });
    renderPanel(WORD_PREVIEW);
    fireEvent.click(screen.getByTestId('office-export-pdf-button'));
    await waitFor(() => {
      expect(mockExportPdf).toHaveBeenCalledWith({
        workspace_path: '/tmp/ws',
        file_path: '/tmp/ws/office/word/doc-word/report.docx',
      });
    });
    await waitFor(() => {
      expect(toastMock.success).toHaveBeenCalledWith(
        '已导出 PDF',
        expect.objectContaining({ description: '/tmp/ws/office/word/doc-word/report.pdf' }),
      );
    });
    expect(toastMock.error).not.toHaveBeenCalled();
  });

  it('maps the missing-converter failure (soffice) to the dedicated message', async () => {
    mockExportPdf.mockResolvedValueOnce({
      ok: false,
      method: null,
      output_path: null,
      error: '未找到 LibreOffice（soffice）；Word COM 回退不可用（仅 Windows 可用）',
    });
    renderPanel(WORD_PREVIEW);
    fireEvent.click(screen.getByTestId('office-export-pdf-button'));
    await waitFor(() => {
      expect(toastMock.error).toHaveBeenCalledWith('未找到本机转换器（需要 LibreOffice 或 MS Word）');
    });
    expect(toastMock.success).not.toHaveBeenCalled();
  });

  it('shows the backend detail for other export failures', async () => {
    mockExportPdf.mockResolvedValueOnce({
      ok: false,
      method: null,
      output_path: null,
      error: 'LibreOffice 转换失败（exit code 9）：boom',
    });
    renderPanel(WORD_PREVIEW);
    fireEvent.click(screen.getByTestId('office-export-pdf-button'));
    await waitFor(() => {
      expect(toastMock.error).toHaveBeenCalledWith(
        '导出失败: LibreOffice 转换失败（exit code 9）：boom',
      );
    });
  });

  it('toasts thrown transport errors', async () => {
    mockExportPdf.mockRejectedValueOnce(new Error('backend down'));
    renderPanel(WORD_PREVIEW);
    fireEvent.click(screen.getByTestId('office-export-pdf-button'));
    await waitFor(() => {
      expect(toastMock.error).toHaveBeenCalledWith('导出失败: backend down');
    });
  });

  it('exposes the edit-preview entry only when the callback is provided', () => {
    const { unmount } = renderPanel(WORD_PREVIEW); // no onEditPreview
    expect(screen.queryByTestId('office-edit-preview-button')).toBeNull();
    unmount();

    const onEditPreview = vi.fn();
    renderPanel(WORD_PREVIEW, onEditPreview);
    fireEvent.click(screen.getByTestId('office-edit-preview-button'));
    expect(onEditPreview).toHaveBeenCalledTimes(1);
  });
});
