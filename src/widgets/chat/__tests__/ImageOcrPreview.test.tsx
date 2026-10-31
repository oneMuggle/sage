import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { ImageOcrPreview } from '../ImageOcrPreview';

const { mocks } = vi.hoisted(() => ({
  mocks: {
    recognize: vi.fn(),
    batch: vi.fn(),
    batchStatus: vi.fn(),
    batchCancel: vi.fn(),
  },
}));

vi.mock('../../../shared/api/ocrApi', () => ({
  ocrApi: {
    recognize: mocks.recognize,
    batch: mocks.batch,
    batchStatus: mocks.batchStatus,
    batchCancel: mocks.batchCancel,
  },
}));

const IMAGE = { name: 'shot.png', dataUrl: 'data:image/png;base64,AAAA' };

function renderPreview(enabled = true, images = [IMAGE]) {
  return render(
    <I18nProvider defaultLocale="zh">
      <ImageOcrPreview images={images} enabled={enabled} />
    </I18nProvider>,
  );
}

describe('ImageOcrPreview', () => {
  beforeEach(() => {
    mocks.recognize.mockReset();
    mocks.batch.mockReset();
    mocks.batchStatus.mockReset();
    mocks.batchCancel.mockReset();
    mocks.batchCancel.mockResolvedValue({ ok: true });
  });

  it('renders recognized text and supports copy', async () => {
    mocks.recognize.mockResolvedValue({
      text: '截图里的文字',
      engine: 'rapidocr',
      quality: 'ok',
    });
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    renderPreview();

    await waitFor(() => {
      expect(screen.getByDisplayValue('截图里的文字')).toBeInTheDocument();
    });
    expect(screen.getByText('rapidocr')).toBeInTheDocument();

    fireEvent.click(screen.getByText('复制'));
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith('截图里的文字');
    });
  });

  it('emits edited text through onTextsChange', async () => {
    mocks.recognize.mockResolvedValue({
      text: '原始文字',
      engine: 'rapidocr',
      quality: 'ok',
    });
    const onTextsChange = vi.fn();

    render(
      <I18nProvider defaultLocale="zh">
        <ImageOcrPreview images={[IMAGE]} enabled onTextsChange={onTextsChange} />
      </I18nProvider>,
    );

    await waitFor(() => {
      expect(screen.getByDisplayValue('原始文字')).toBeInTheDocument();
    });
    fireEvent.change(screen.getByDisplayValue('原始文字'), {
      target: { value: '用户编辑后的文字' },
    });

    await waitFor(() => {
      expect(onTextsChange).toHaveBeenLastCalledWith([
        { dataUrl: IMAGE.dataUrl, text: '用户编辑后的文字' },
      ]);
    });
  });

  it('renders nothing when disabled', () => {
    renderPreview(false);

    expect(screen.queryByTestId('chat-image-ocr-preview')).not.toBeInTheDocument();
  });

  it('shows empty and failure states through the batch queue', async () => {
    mocks.batch.mockResolvedValue({ job_id: 'job-1', total: 2 });
    mocks.batchStatus.mockResolvedValue({
      job_id: 'job-1',
      status: 'completed',
      total: 2,
      completed: 2,
      failed: 1,
      error: null,
      results: [
        { index: 0, text: '', engine: 'rapidocr', quality: 'empty', error: null },
        {
          index: 1,
          text: '',
          engine: 'rapidocr',
          quality: 'failed',
          error: 'engine down',
        },
      ],
    });

    renderPreview(true, [IMAGE, { ...IMAGE, name: 'second.png' }]);

    await waitFor(() => {
      expect(mocks.batch).toHaveBeenCalledTimes(1);
      expect(screen.getByText('未识别到文字')).toBeInTheDocument();
      expect(screen.getByText(/识别失败：engine down/)).toBeInTheDocument();
    });
    expect(mocks.recognize).not.toHaveBeenCalled();
  });

  it('re-runs OCR when retry is clicked', async () => {
    mocks.recognize.mockResolvedValue({ text: '结果', engine: 'rapidocr', quality: 'ok' });

    renderPreview();
    await waitFor(() => expect(mocks.recognize).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByLabelText('重新识别'));

    await waitFor(() => expect(mocks.recognize).toHaveBeenCalledTimes(2));
  });
});
