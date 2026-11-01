import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  auditLatexPdf,
  type LatexPdfAuditResult,
} from '../../../shared/api/latexApi';
import { LatexPdfAuditPanel } from '../LatexPdfAuditPanel';

vi.mock('../../../shared/api/latexApi', () => ({
  auditLatexPdf: vi.fn(),
}));

const mockedAudit = vi.mocked(auditLatexPdf);

const RESULT: LatexPdfAuditResult = {
  ok: false,
  source_path: 'paper/main.pdf',
  summary: {
    pages: 2,
    page_size: { width: 595.3, height: 841.9, label: 'A4' },
    page_sizes: [{ width: 595.3, height: 841.9, pages: [1, 2] }],
    fonts: [
      {
        basefont: 'Helvetica',
        type: 'Type1',
        ext: 'n/a',
        embedded: false,
        pages: [1],
      },
    ],
    images_count: 0,
    min_image_dpi: null,
  },
  issues: [
    {
      rule_id: 'PDF-FONT-NOT-EMBEDDED',
      severity: 'error',
      category: 'pdf-font',
      message: '字体未嵌入: Helvetica',
      fix_hint: '导出 PDF 时选择嵌入全部字体',
      anchor: { file: 'paper/main.pdf', page: 1 },
    },
  ],
};

afterEach(() => {
  vi.clearAllMocks();
});

describe('LatexPdfAuditPanel', () => {
  it('audits a PDF and renders page/font findings', async () => {
    mockedAudit.mockResolvedValue(RESULT);

    render(<LatexPdfAuditPanel workspacePath="/ws" />);

    fireEvent.change(screen.getByTestId('latex-pdf-path'), {
      target: { value: 'paper/main.pdf' },
    });
    fireEvent.change(screen.getByTestId('latex-pdf-min-pages'), {
      target: { value: '3' },
    });
    fireEvent.click(screen.getByTestId('latex-pdf-run'));

    await waitFor(() =>
      expect(mockedAudit).toHaveBeenCalledWith(
        '/ws',
        '/ws/paper/main.pdf',
        3,
        undefined,
        150,
      ),
    );
    const result = screen.getByTestId('latex-pdf-result');
    expect(result).toHaveTextContent('共 2 页');
    expect(result).toHaveTextContent('A4');
    expect(result).toHaveTextContent('PDF-FONT-NOT-EMBEDDED');
    expect(result).toHaveTextContent('第 1 页');
  });

  it('shows backend errors', async () => {
    mockedAudit.mockRejectedValue(new Error('PDF 已加密，拒绝审计'));

    render(<LatexPdfAuditPanel workspacePath="/ws" />);

    fireEvent.change(screen.getByTestId('latex-pdf-path'), {
      target: { value: 'locked.pdf' },
    });
    fireEvent.click(screen.getByTestId('latex-pdf-run'));

    await waitFor(() =>
      expect(screen.getByText('PDF 已加密，拒绝审计')).toBeTruthy(),
    );
  });
});
