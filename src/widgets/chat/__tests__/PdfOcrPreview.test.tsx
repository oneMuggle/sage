import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { PdfOcrPreview } from '../PdfOcrPreview';

const { mocks } = vi.hoisted(() => ({
  mocks: {
    batchPdf: vi.fn(),
    batchStatus: vi.fn(),
    batchCancel: vi.fn(),
  },
}));

vi.mock('../../../shared/api/ocrApi', () => ({
  ocrApi: {
    batchPdf: mocks.batchPdf,
    batchStatus: mocks.batchStatus,
    batchCancel: mocks.batchCancel,
  },
}));

const target = {
  name: 'report.pdf',
  dataUrl: 'data:application/pdf;base64,AAAA',
};

function renderPreview(onClose = vi.fn()) {
  render(
    <I18nProvider defaultLocale="zh">
      <PdfOcrPreview target={target} onClose={onClose} />
    </I18nProvider>,
  );
  return { onClose };
}

describe('PdfOcrPreview', () => {
  beforeEach(() => {
    mocks.batchPdf.mockResolvedValue({
      job_id: 'job-1',
      total: 2,
      pages: 2,
      source: 'pdf',
    });
    mocks.batchStatus.mockResolvedValue({
      job_id: 'job-1',
      status: 'completed',
      source: 'pdf',
      total: 2,
      completed: 2,
      failed: 0,
      error: null,
      results: [
        { index: 0, text: '第一页文字', engine: 'fake', quality: 'ok', error: null },
        { index: 1, text: '第二页文字', engine: 'fake', quality: 'ok', error: null },
      ],
    });
    mocks.batchCancel.mockResolvedValue({ ok: true });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('renders page-level OCR text and progress', async () => {
    renderPreview();

    await waitFor(() => {
      expect(screen.getByText('第一页文字')).toBeInTheDocument();
    });
    expect(screen.getByText('第二页文字')).toBeInTheDocument();
    expect(screen.getByText('2/2 页')).toBeInTheDocument();
    expect(mocks.batchPdf).toHaveBeenCalledWith(target.dataUrl);
  });

  it('retries the PDF OCR job', async () => {
    renderPreview();
    await waitFor(() => {
      expect(screen.getByText('第一页文字')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('pdf-ocr-retry'));

    await waitFor(() => {
      expect(mocks.batchPdf).toHaveBeenCalledTimes(2);
    });
  });

  it('calls onClose from the close button', async () => {
    const { onClose } = renderPreview();
    await waitFor(() => {
      expect(screen.getByText('第一页文字')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('pdf-ocr-close'));

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
