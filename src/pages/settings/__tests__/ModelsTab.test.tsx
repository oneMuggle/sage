// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { DEFAULT_SETTINGS, type ModelCapability } from '../../../entities/setting/types';
import { I18nProvider } from '../../../shared/lib/i18n';
import { formatModelsTabAuditJson, formatModelsTabAuditSnapshot, ModelsTab } from '../ModelsTab';

vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn() }));

const settings = {
  ...DEFAULT_SETTINGS,
  endpoints: [
    {
      id: 'ep-1',
      name: 'Test',
      baseUrl: 'http://localhost',
      apiKey: '',
      protocol: 'openai-compatible' as const,
      modelId: '',
      localModelPath: '',
      discoveredModels: [
        { id: 'model-1', capabilities: ['chat'] as ModelCapability[], endpointId: 'ep-1' },
      ],
      lastDiscoveredAt: null,
    },
  ],
  modelSelections: {
    chatModel: { endpointId: 'ep-1', modelId: 'model-1' },
    visionModel: { endpointId: null, modelId: null },
    embeddingModel: { endpointId: null, modelId: null },
    ttsModel: { endpointId: null, modelId: null },
    asrModel: { endpointId: null, modelId: null },
    imageGenModel: { endpointId: null, modelId: null },
  },
  maxContext: 4096,
  autoContext: true,
  temperature: 0.7,
};

function renderTab(updateSettings = vi.fn()) {
  return render(
    <I18nProvider defaultLocale="zh">
      <ModelsTab settings={settings} updateSettings={updateSettings} />
    </I18nProvider>,
  );
}

describe('ModelsTab context controls', () => {
  it('disables the fixed context input in automatic mode', () => {
    renderTab();
    expect(screen.getByTestId('settings-max-context')).toBeDisabled();
  });

  it('renders max output tokens and writes it back on change', () => {
    const updateSettings = vi.fn();
    renderTab(updateSettings);

    const input = screen.getByTestId('settings-max-output-tokens');
    expect(input).toHaveValue(4096);
    expect(input).toHaveAttribute('min', '512');
    expect(input).toHaveAttribute('max', '32768');

    fireEvent.change(input, { target: { value: '8192' } });
    expect(updateSettings).toHaveBeenCalledWith({ maxOutputTokens: 8192 });
  });

  it('uses the corrected Temperature description', () => {
    renderTab();
    expect(screen.getByText(/0 最稳定，2 最随机/)).toBeInTheDocument();
  });

  it('exports ModelsTab audit snapshot and JSON helpers; copy controls moved to the audit export tab (P3)', () => {
    const snapshot = formatModelsTabAuditSnapshot({
      endpointCount: 1,
      discoveredModelCount: 3,
      chatModel: 'model-1',
      visionModel: null,
      embeddingModel: 'emb-1',
      maxContext: 4096,
      autoContext: true,
      temperature: 0.7,
    });
    expect(snapshot).toContain('# 模型选择审计快照');
    expect(snapshot).toContain('对话模型: model-1');
    expect(snapshot).toContain('上下文模式: 自动推断');

    const json = JSON.parse(
      formatModelsTabAuditJson({
        endpointCount: 1,
        discoveredModelCount: 1,
        chatModel: 'model-1',
        visionModel: null,
        embeddingModel: null,
        maxContext: 8192,
        autoContext: false,
        temperature: 0.2,
      }),
    );
    expect(json).toEqual({
      endpointCount: 1,
      discoveredModelCount: 1,
      chatModel: 'model-1',
      visionModel: null,
      embeddingModel: null,
      maxContext: 8192,
      autoContext: false,
      temperature: 0.2,
    });
  });
});

describe('ModelsTab routing mode (Task 11)', () => {
  const autoSettings = { ...settings, routing: { mode: 'auto' as const } };

  it('defaults to manual mode and renders no read-only routing table', () => {
    render(<ModelsTab settings={settings} updateSettings={vi.fn()} />);

    expect(screen.getByTestId('settings-routing-mode-manual')).toBeChecked();
    expect(screen.getByTestId('settings-routing-mode-auto')).not.toBeChecked();
    expect(screen.queryByTestId('settings-routing-table')).toBeNull();
  });

  it('writes routing.mode when the auto radio is selected', () => {
    const updateSettings = vi.fn();
    render(<ModelsTab settings={settings} updateSettings={updateSettings} />);

    fireEvent.click(screen.getByTestId('settings-routing-mode-auto'));

    expect(updateSettings).toHaveBeenCalledWith(
      expect.objectContaining({ routing: expect.objectContaining({ mode: 'auto' }) }),
    );
  });

  it('auto mode shows the mapping table + chat endpoint row and hides the chat picker', () => {
    render(<ModelsTab settings={autoSettings} updateSettings={vi.fn()} />);

    const table = screen.getByTestId('settings-routing-table');
    const rows = Array.from(table.querySelectorAll('tbody tr'));
    expect(rows).toHaveLength(9);
    const codeReviewRow = rows.find((row) => row.textContent?.includes('代码审查'));
    expect(codeReviewRow?.textContent).toContain('强力');
    expect(screen.getByTestId('settings-routing-endpoint')).toHaveTextContent('Test');
    expect(screen.queryByText('用于文本对话（必填）')).toBeNull();
  });

  it('auto mode keeps the other five capability selectors', () => {
    // 6 个能力选择器 (手动: chat/vision/embedding/tts/asr/image_gen) → 自动模式
    // 隐藏 chat 选择器剩 5 个。无其它 <select> 干扰, 直接全量计数。
    const capabilitySelects = (container: HTMLElement) =>
      container.querySelectorAll('select');

    const manual = render(<ModelsTab settings={settings} updateSettings={vi.fn()} />);
    expect(capabilitySelects(manual.container)).toHaveLength(6);
    manual.unmount();

    const auto = render(<ModelsTab settings={autoSettings} updateSettings={vi.fn()} />);
    expect(capabilitySelects(auto.container)).toHaveLength(5);
  });

  it('keeps the routing switch reachable when no endpoint has models (R31a)', () => {
    const emptySettings = { ...settings, endpoints: [] };
    render(<ModelsTab settings={emptySettings} updateSettings={vi.fn()} />);

    expect(screen.getByTestId('settings-routing-mode-auto')).toBeInTheDocument();
    expect(screen.getByTestId('settings-routing-mode-manual')).toBeChecked();
    expect(screen.getByText(/请先在/)).toBeInTheDocument();
  });
});
