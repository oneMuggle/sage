import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { ChatInput } from '../ChatInput';

const { ocrState, settingsState, catalogState } = vi.hoisted(() => ({
  ocrState: { available: true, enabled: true },
  settingsState: {
    chatModel: { endpointId: 'e1', modelId: 'text-only' },
    discoveredModels: [{ id: 'text-only', capabilities: ['chat'] }] as {
      id: string;
      capabilities: string[];
    }[],
  },
  catalogState: { effective: null as unknown },
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

vi.mock('../../../entities/model-catalog/api', () => ({
  getEffective: vi.fn(() => Promise.resolve(catalogState.effective)),
}));

vi.mock('../../../features/manage-settings/useSettings', () => ({
  useSettings: () => ({
    settings: {
      modelSelections: {
        chatModel: settingsState.chatModel,
        visionModel: { endpointId: '', modelId: '' },
      },
      endpoints: [
        {
          id: 'e1',
          discoveredModels: settingsState.discoveredModels,
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

beforeEach(() => {
  ocrState.available = true;
  ocrState.enabled = true;
  settingsState.chatModel = { endpointId: 'e1', modelId: 'text-only' };
  settingsState.discoveredModels = [{ id: 'text-only', capabilities: ['chat'] }];
  catalogState.effective = null;
});

describe('ChatInput — local OCR fallback', () => {
  it('keeps image upload enabled and shows OCR notice when OCR is available', async () => {
    renderWithI18n();

    await waitFor(() => {
      expect(screen.getByTestId('chat-ocr-fallback-banner')).toBeInTheDocument();
    });
    expect(screen.queryByText(/请配置视觉理解模型/)).not.toBeInTheDocument();
  });

  it('still warns and disables upload when no OCR is available', async () => {
    ocrState.available = false;
    renderWithI18n();

    await waitFor(() => {
      expect(screen.getByText(/请配置视觉理解模型/)).toBeInTheDocument();
    });
    expect(screen.queryByTestId('chat-ocr-fallback-banner')).not.toBeInTheDocument();
  });
});

describe('ChatInput — vision capability resolution', () => {
  it('treats catalog-supported model as vision-capable even when discovery missed it', async () => {
    catalogState.effective = { capabilities: { vision: true } };
    renderWithI18n();

    await waitFor(() => {
      expect(screen.queryByText(/请配置视觉理解模型/)).not.toBeInTheDocument();
    });
    expect(screen.queryByTestId('chat-ocr-fallback-banner')).not.toBeInTheDocument();
  });

  it('treats discovery-reported vision as supported', async () => {
    settingsState.discoveredModels = [{ id: 'text-only', capabilities: ['chat', 'vision'] }];
    renderWithI18n();

    await waitFor(() => {
      expect(screen.queryByText(/请配置视觉理解模型/)).not.toBeInTheDocument();
    });
    expect(screen.queryByTestId('chat-ocr-fallback-banner')).not.toBeInTheDocument();
  });

  it('fails open when the model is unknown to both catalog and discovery', async () => {
    ocrState.available = false;
    settingsState.discoveredModels = [];
    renderWithI18n();

    await waitFor(() => {
      expect(screen.queryByText(/请配置视觉理解模型/)).not.toBeInTheDocument();
    });
  });
});
