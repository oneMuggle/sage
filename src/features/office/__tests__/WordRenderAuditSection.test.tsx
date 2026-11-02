import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { officeApi } from '../../../shared/api/officeApi';
import type { WordRenderAuditResult } from '../../../shared/api/wordAuditTypes';
import { WordRenderAuditSection } from '../WordRenderAuditSection';

vi.mock('../../../shared/api/officeApi', () => ({
  officeApi: {
    renderAuditWord: vi.fn(),
  },
}));

const mockedRenderAudit = vi.mocked(officeApi.renderAuditWord);

const RENDERED: WordRenderAuditResult = {
  ok: false,
  source_path: '/ws/doc.docx',
  rendered: true,
  method: 'libreoffice',
  page_count: 2,
  issues: [
    {
      page_index: 0,
      category: 'margin',
      severity: 'error',
      message: '左边距不足',
      expected: '3.7cm',
      actual: '2.5cm',
    },
    {
      page_index: 1,
      category: 'font',
      severity: 'warning',
      message: '使用了非白名单字体 SimSun',
      actual: 'SimSun',
    },
  ],
  warnings: [],
};

const UNRENDERED: WordRenderAuditResult = {
  ok: true,
  source_path: '/ws/doc.docx',
  rendered: false,
  method: null,
  page_count: 0,
  issues: [],
  warnings: [{ code: 'render_unavailable', message: '未找到 DOCX→PDF 转换器' }],
};

afterEach(() => {
  vi.clearAllMocks();
});

describe('WordRenderAuditSection', () => {
  it('sends the configured options and renders grouped issues', async () => {
    mockedRenderAudit.mockResolvedValue(RENDERED);

    render(<WordRenderAuditSection workspacePath="/ws" filePath="/ws/doc.docx" />);

    fireEvent.change(screen.getByTestId('word-render-size'), { target: { value: 'A4' } });
    fireEvent.change(screen.getByTestId('word-render-fonts'), {
      target: { value: '宋体, Times New Roman' },
    });
    fireEvent.change(screen.getByTestId('word-render-margin-top'), { target: { value: '3.7' } });
    fireEvent.click(screen.getByTestId('word-render-page-number'));
    fireEvent.click(screen.getByTestId('word-render-run'));

    await waitFor(() => expect(screen.getByTestId('word-render-result')).toBeInTheDocument());
    expect(mockedRenderAudit).toHaveBeenCalledWith({
      workspace_path: '/ws',
      file_path: '/ws/doc.docx',
      expected_size: 'A4',
      margins_cm: { top: 3.7 },
      allowed_fonts: ['宋体', 'Times New Roman'],
      require_page_number: true,
    });
    expect(screen.getByTestId('word-render-summary')).toHaveTextContent('已渲染 2 页');
    expect(screen.getByTestId('word-render-issue-0')).toHaveTextContent('页边距');
    expect(screen.getByTestId('word-render-issue-0')).toHaveTextContent('第 1 页');
    expect(screen.getByTestId('word-render-issue-1')).toHaveTextContent('字体');
  });

  it('degrades gracefully when no converter is available', async () => {
    mockedRenderAudit.mockResolvedValue(UNRENDERED);

    render(<WordRenderAuditSection workspacePath="/ws" filePath="/ws/doc.docx" />);
    fireEvent.click(screen.getByTestId('word-render-run'));

    await waitFor(() => expect(screen.getByTestId('word-render-unrendered')).toBeInTheDocument());
    expect(screen.queryByTestId('word-render-issues')).toBeNull();
    expect(screen.getByTestId('word-render-warnings')).toHaveTextContent('render_unavailable');
  });

  it('shows an error message when the request fails', async () => {
    mockedRenderAudit.mockRejectedValue(new Error('converter crashed'));

    render(<WordRenderAuditSection workspacePath="/ws" filePath="/ws/doc.docx" />);
    fireEvent.click(screen.getByTestId('word-render-run'));

    await waitFor(() => expect(screen.getByTestId('word-render-error')).toBeInTheDocument());
    expect(screen.getByText('converter crashed')).toBeInTheDocument();
  });
});
