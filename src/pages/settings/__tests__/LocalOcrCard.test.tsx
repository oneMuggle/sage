import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { LocalOcrCard } from '../LocalOcrCard';

const { mocks } = vi.hoisted(() => ({
  mocks: {
    capabilities: vi.fn(),
    recognize: vi.fn(),
    reload: vi.fn(),
    getPreference: vi.fn(),
    setPreference: vi.fn(),
  },
}));

vi.mock('../../../shared/api/ocrApi', () => ({
  ocrApi: {
    capabilities: mocks.capabilities,
    recognize: mocks.recognize,
    reload: mocks.reload,
  },
}));

vi.mock('../../../shared/api/settingsClient', () => ({
  settingsClient: {
    getPreference: mocks.getPreference,
    setPreference: mocks.setPreference,
  },
}));

function renderCard() {
  return render(
    <I18nProvider defaultLocale="zh">
      <LocalOcrCard />
    </I18nProvider>,
  );
}

describe('LocalOcrCard', () => {
  afterEach(() => {
    delete (window as { electronAPI?: unknown }).electronAPI;
  });

  it('shows engine status and persists prefer_local_for_images', async () => {
    mocks.capabilities.mockResolvedValue({
      enabled: true,
      available: true,
      selected_engine: 'rapidocr',
      reason: '',
    });
    mocks.getPreference.mockResolvedValue(
      JSON.stringify({
        enabled: true,
        engine: 'auto',
        lang: 'auto',
        prefer_local_for_images: false,
      }),
    );
    mocks.setPreference.mockResolvedValue(undefined);

    renderCard();

    await waitFor(() => {
      expect(screen.getByText(/可用（rapidocr）/)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('settings-ocr-prefer-local'));

    await waitFor(() => {
      expect(mocks.setPreference).toHaveBeenCalledWith(
        'ocr_config',
        expect.stringContaining('"prefer_local_for_images":true'),
        'ocr',
      );
    });
  });

  it('persists office_enabled toggle', async () => {
    mocks.capabilities.mockResolvedValue({
      enabled: true,
      available: true,
      selected_engine: 'rapidocr',
      reason: '',
    });
    mocks.getPreference.mockResolvedValue(null);
    mocks.setPreference.mockResolvedValue(undefined);

    renderCard();

    await waitFor(() => {
      expect(screen.getByTestId('settings-ocr-office')).not.toBeChecked();
    });
    fireEvent.click(screen.getByTestId('settings-ocr-office'));

    await waitFor(() => {
      expect(mocks.setPreference).toHaveBeenCalledWith(
        'ocr_config',
        expect.stringContaining('"office_enabled":true'),
        'ocr',
      );
    });
  });

  it('downloads the tiny OCR model and reloads capabilities', async () => {
    mocks.capabilities.mockResolvedValue({
      enabled: true,
      available: true,
      selected_engine: 'rapidocr',
      reason: '',
    });
    mocks.getPreference.mockResolvedValue(null);
    mocks.reload.mockResolvedValue({ enabled: true, available: true });
    const downloadOcr = vi.fn().mockResolvedValue({ ok: true, totalBytes: 6_200_000 });
    const resetOcr = vi.fn().mockResolvedValue({ ok: true });
    Object.defineProperty(window, 'electronAPI', {
      configurable: true,
      value: {
        modelDownload: { downloadOcr, resetOcr },
        listen: vi.fn().mockResolvedValue(() => undefined),
      },
    });

    renderCard();

    await waitFor(() => {
      expect(screen.getByTestId('settings-ocr-download')).not.toBeDisabled();
    });
    fireEvent.click(screen.getByTestId('settings-ocr-download'));

    await waitFor(() => {
      expect(downloadOcr).toHaveBeenCalledTimes(1);
      expect(mocks.reload).toHaveBeenCalledTimes(1);
    });
    expect(screen.getByTestId('settings-ocr-model-status')).toHaveTextContent(
      '已启用 tiny 模型',
    );
  });

  it('cancels an in-flight OCR model download', async () => {
    mocks.capabilities.mockResolvedValue({
      enabled: true,
      available: true,
      selected_engine: 'rapidocr',
      reason: '',
    });
    mocks.getPreference.mockResolvedValue(null);
    let resolveDownload:
      | ((value: { ok: boolean; error?: string }) => void)
      | undefined;
    const downloadOcr = vi.fn(
      () =>
        new Promise<{ ok: boolean; error?: string }>((resolve) => {
          resolveDownload = resolve;
        }),
    );
    const cancelOcr = vi.fn().mockResolvedValue({ ok: true });
    const resetOcr = vi.fn().mockResolvedValue({ ok: true });
    Object.defineProperty(window, 'electronAPI', {
      configurable: true,
      value: {
        modelDownload: { downloadOcr, cancelOcr, resetOcr },
        listen: vi.fn().mockResolvedValue(() => undefined),
      },
    });

    renderCard();

    await waitFor(() => {
      expect(screen.getByTestId('settings-ocr-download')).not.toBeDisabled();
    });
    fireEvent.click(screen.getByTestId('settings-ocr-download'));

    await waitFor(() => {
      expect(screen.getByTestId('settings-ocr-cancel-download')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId('settings-ocr-cancel-download'));

    await waitFor(() => {
      expect(cancelOcr).toHaveBeenCalledTimes(1);
    });
    resolveDownload?.({ ok: false, error: 'cancelled' });

    await waitFor(() => {
      expect(screen.getByTestId('settings-ocr-model-status')).toHaveTextContent(
        '已取消下载',
      );
    });
  });

  it('runs the built-in OCR test image', async () => {
    mocks.capabilities.mockResolvedValue({
      enabled: true,
      available: true,
      selected_engine: 'rapidocr',
      reason: '',
    });
    mocks.getPreference.mockResolvedValue(null);
    mocks.recognize.mockResolvedValue({ text: 'SAGE OCR 123' });

    renderCard();

    await waitFor(() => {
      expect(screen.getByTestId('settings-ocr-test')).not.toBeDisabled();
    });
    fireEvent.click(screen.getByTestId('settings-ocr-test'));

    await waitFor(() => {
      expect(screen.getByTestId('settings-ocr-test-result')).toHaveTextContent('SAGE OCR 123');
    });
    expect(mocks.recognize).toHaveBeenCalledWith(expect.stringContaining('data:image/png'));
  });

  it('shows unavailable hint when no engine is present', async () => {
    mocks.capabilities.mockResolvedValue({
      enabled: true,
      available: false,
      selected_engine: null,
      reason: 'rapidocr 未安装',
    });
    mocks.getPreference.mockResolvedValue(null);

    renderCard();

    await waitFor(() => {
      expect(screen.getByText('不可用')).toBeInTheDocument();
    });
    expect(screen.getByText('rapidocr 未安装')).toBeInTheDocument();
  });
});
