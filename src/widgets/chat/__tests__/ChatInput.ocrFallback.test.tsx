import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { emitSessionModelOverrideChanged } from '../../../shared/lib/effectiveChatModel';
import { I18nProvider } from '../../../shared/lib/i18n';
import { ChatInput } from '../ChatInput';

const { ocrState, settingsState, catalogState, overrideState, sessionState, workspaceState } =
  vi.hoisted(() => ({
    ocrState: { available: true, enabled: true },
    settingsState: {
      chatModel: { endpointId: 'e1', modelId: 'text-only' },
      discoveredModels: [{ id: 'text-only', capabilities: ['chat'] }] as {
        id: string;
        capabilities: string[];
      }[],
    },
    catalogState: { effective: null as unknown },
    overrideState: { calls: [] as unknown[][] },
    sessionState: { override: null as string | null, calls: [] as string[] },
    workspaceState: { sessionId: 'session-1' as string | null },
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
  getEffective: vi.fn((_endpointId: string, modelId: string) =>
    Promise.resolve(
      modelId === 'vision-model'
        ? { capabilities: { vision: true }, revision: 1 }
        : catalogState.effective,
    ),
  ),
  setOverride: vi.fn(
    (
      endpointId: string,
      modelId: string,
      patch: unknown,
      expectedRevision: number,
    ): Promise<{ revision: number }> => {
      overrideState.calls.push([endpointId, modelId, patch, expectedRevision]);
      catalogState.effective = { capabilities: { vision: true }, revision: 1 };
      return Promise.resolve({ revision: 1 });
    },
  ),
}));

vi.mock('../../../shared/api/sessionApi', () => ({
  sessionApi: {
    getModelOverride: vi.fn((sessionId: string) => {
      sessionState.calls.push(sessionId);
      return Promise.resolve(sessionState.override);
    }),
  },
}));

vi.mock('../../../shared/lib/workspaceContext', () => ({
  useOptionalWorkspaceContext: () => ({
    sessionId: workspaceState.sessionId,
    binding: null,
  }),
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
  overrideState.calls = [];
  sessionState.override = null;
  sessionState.calls = [];
  workspaceState.sessionId = 'session-1';
});

describe('ChatInput — local OCR fallback', () => {
  it('keeps image upload enabled and shows OCR notice when OCR is available', async () => {
    // 只有权威源明确 vision=false 才进入 OCR 回退路径；启发式未命中按未知放行。
    catalogState.effective = { capabilities: { vision: false } };
    renderWithI18n();

    await waitFor(() => {
      expect(screen.getByTestId('chat-ocr-fallback-banner')).toBeInTheDocument();
    });
    expect(screen.queryByText(/请配置视觉理解模型/)).not.toBeInTheDocument();
  });

  it('still warns and disables upload when vision is explicitly unsupported and no OCR exists', async () => {
    ocrState.available = false;
    catalogState.effective = { capabilities: { vision: false } };
    renderWithI18n();

    await waitFor(() => {
      expect(screen.getByText(/请配置视觉理解模型/)).toBeInTheDocument();
    });
    expect(screen.queryByTestId('chat-ocr-fallback-banner')).not.toBeInTheDocument();
  });

  it('does not block a model whose heuristic marker missed vision', async () => {
    // 回归：deepseek-flash 这类名字未命中 marker 的多模态模型曾被伪判 unsupported。
    ocrState.available = false;
    catalogState.effective = null;
    settingsState.discoveredModels = [{ id: 'text-only', capabilities: ['chat'] }];
    renderWithI18n();

    await waitFor(() => {
      expect(screen.queryByText(/请配置视觉理解模型/)).not.toBeInTheDocument();
    });
    expect(screen.queryByTestId('chat-ocr-fallback-banner')).not.toBeInTheDocument();
  });
});

describe('ChatInput — user correction of vision capability', () => {
  it('writes a catalog override and unblocks upload after marking vision supported', async () => {
    ocrState.available = false;
    catalogState.effective = { capabilities: { vision: false }, revision: 3 };
    renderWithI18n();

    const button = await screen.findByRole('button', { name: /标记为支持图片/ });
    fireEvent.click(button);

    await waitFor(() => {
      expect(screen.queryByText(/请配置视觉理解模型/)).not.toBeInTheDocument();
    });
    expect(overrideState.calls[0]).toEqual([
      'e1',
      'text-only',
      { capabilities: { vision: true } },
      3,
    ]);
  });

  it('judges vision by the session override model, not the global model', async () => {
    ocrState.available = false;
    catalogState.effective = { capabilities: { vision: false }, revision: 1 };
    settingsState.discoveredModels = [
      { id: 'text-only', capabilities: ['chat'] },
      { id: 'vision-model', capabilities: ['chat', 'vision'] },
    ];
    sessionState.override = 'vision-model';
    renderWithI18n();

    // 覆盖路径必须真实执行（workspace context 提供 sessionId）。
    await waitFor(() => expect(sessionState.calls).toContain('session-1'));
    await waitFor(() => {
      expect(screen.queryByText(/请配置视觉理解模型/)).not.toBeInTheDocument();
    });
  });

  it('refreshes vision support when the session model changes in place', async () => {
    ocrState.available = false;
    catalogState.effective = { capabilities: { vision: false }, revision: 1 };
    settingsState.discoveredModels = [
      { id: 'text-only', capabilities: ['chat'] },
      { id: 'vision-model', capabilities: ['chat', 'vision'] },
    ];
    renderWithI18n();

    await waitFor(() => {
      expect(screen.getByText(/请配置视觉理解模型/)).toBeInTheDocument();
    });

    act(() => {
      emitSessionModelOverrideChanged({ sessionId: 'session-1', modelId: 'vision-model' });
    });

    await waitFor(() => {
      expect(screen.queryByText(/请配置视觉理解模型/)).not.toBeInTheDocument();
    });
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
