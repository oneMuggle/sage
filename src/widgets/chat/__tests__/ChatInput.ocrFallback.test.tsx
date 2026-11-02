import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { ChatInput } from '../ChatInput';

const { ocrState } = vi.hoisted(() => ({
  ocrState: { available: true, enabled: true },
}));

vi.mock('../../../shared/lib/hooks/useFileUpload', () => ({
  useFileUpload: () => ({
    files: [],
    images: [],
    addFile: vi.fn(),
    addImage: vi.fn(),
    removeFile: vi.fn(),
    removeImage: vi.fn(),
    clearAll: vi.fn(),
    handleDrop: vi.fn(),
    handleDragOver: vi.fn(),
    isDragOver: false,
  }),
}));

vi.mock('../../../features/manage-settings/useSettings', () => ({
  useSettings: () => ({
    settings: {
      modelSelections: {
        chatModel: { endpointId: 'e1', modelId: 'text-only' },
        visionModel: { endpointId: '', modelId: '' },
      },
      endpoints: [
        {
          id: 'e1',
          discoveredModels: [{ id: 'text-only', capabilities: ['chat'] }],
        },
      ],
    },
  }),
}));

vi.mock('../../../shared/api/ocrApi', () => ({
  ocrApi: {
    capabilities: vi.fn(() =>
      Promise.resolve({
        enabled: ocrState.enabled,
        available: ocrState.available,
        engine: 'auto',
        selected_engine: 'fake',
        reason: '',
        lang: 'auto',
        prefer_local_for_images: false,
        engines: [],
        languages: null,
      }),
    ),
  },
}));

const renderWithI18n = () =>
  render(
    <I18nProvider defaultLocale="zh">
      <ChatInput onSend={vi.fn()} />
    </I18nProvider>,
  );

describe('ChatInput — local OCR fallback', () => {
  it('keeps image upload enabled and shows OCR notice when OCR is available', async () => {
    ocrState.available = true;
    ocrState.enabled = true;
    renderWithI18n();

    await waitFor(() => {
      expect(screen.getByTestId('chat-ocr-fallback-banner')).toBeInTheDocument();
    });
    expect(screen.queryByText(/请配置视觉理解模型/)).not.toBeInTheDocument();
  });

  it('still warns and disables upload when no OCR is available', async () => {
    ocrState.available = false;
    ocrState.enabled = true;
    renderWithI18n();

    await waitFor(() => {
      expect(screen.getByText(/请配置视觉理解模型/)).toBeInTheDocument();
    });
    expect(screen.queryByTestId('chat-ocr-fallback-banner')).not.toBeInTheDocument();
  });
});
