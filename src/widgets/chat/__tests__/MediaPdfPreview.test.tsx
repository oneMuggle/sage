/**
 * 聊天附件 PDF 原文预览单测（2026-11-15）。
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { MediaPdfPreview } from '../MediaPdfPreview';

const mocks = vi.hoisted(() => ({
  fetchMediaBlobUrl: vi.fn(async () => 'blob:pdf-1'),
  revokeMediaBlobUrl: vi.fn(),
}));

vi.mock('../../../shared/api/mediaApi', () => ({
  fetchMediaBlobUrl: mocks.fetchMediaBlobUrl,
  revokeMediaBlobUrl: mocks.revokeMediaBlobUrl,
}));

function renderPreview(props: Partial<React.ComponentProps<typeof MediaPdfPreview>> = {}) {
  return render(
    <I18nProvider defaultLocale="zh">
      <MediaPdfPreview mediaId="abc123" filename="paper.pdf" onClose={vi.fn()} {...props} />
    </I18nProvider>,
  );
}

describe('MediaPdfPreview', () => {
  beforeEach(() => {
    mocks.fetchMediaBlobUrl.mockClear();
    mocks.fetchMediaBlobUrl.mockImplementation(async () => 'blob:pdf-1');
    mocks.revokeMediaBlobUrl.mockClear();
  });

  it('加载媒体 blob 并用 #page 定位', async () => {
    renderPreview({ page: 12 });
    const iframe = await screen.findByTestId('media-pdf-iframe');
    expect(iframe).toHaveAttribute('src', 'blob:pdf-1#page=12');
    expect(mocks.fetchMediaBlobUrl).toHaveBeenCalledWith('abc123', 'application/pdf');
    expect(screen.getByText(/paper\.pdf/)).toBeInTheDocument();
    expect(screen.getByText(/12 页/)).toBeInTheDocument();
  });

  it('ESC 关闭', async () => {
    const onClose = vi.fn();
    renderPreview({ onClose });
    await screen.findByTestId('media-pdf-iframe');
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('关闭按钮回调', async () => {
    const onClose = vi.fn();
    renderPreview({ onClose });
    await screen.findByTestId('media-pdf-iframe');
    fireEvent.click(screen.getByTestId('media-pdf-preview-close'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('拉取失败显示失败占位', async () => {
    mocks.fetchMediaBlobUrl.mockRejectedValueOnce(new Error('ipc down'));
    renderPreview();
    expect(await screen.findByText('PDF 预览失败')).toBeInTheDocument();
  });
});
