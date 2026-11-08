// @vitest-environment jsdom
/**
 * P0-A (2026-09-18): 最大上下文长度编辑器 — 档位下拉 + 自定义(数值+K/M单位)。
 * 回归钉: 旧版 number input 硬编码 max=128000, 512K/1M 无法输入。
 */
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
      reasoningEffort: null,
      thinkingBudget: null,
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

function renderTab(updateSettings = vi.fn(), settingsOverride: typeof settings = settings) {
  return render(
    <I18nProvider defaultLocale="zh">
      <ModelsTab settings={settingsOverride} updateSettings={updateSettings} />
    </I18nProvider>,
  );
}

describe('ModelsTab context controls', () => {
  it('disables the context length control in automatic mode', () => {
    renderTab();
    expect(screen.getByLabelText('最大上下文长度档位')).toBeDisabled();
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

describe('ModelsTab 上下文长度编辑器', () => {
  const fixedContext = { ...settings, autoContext: false };

  it('档位下拉包含 512K / 1M / 2M (回归钉: 旧 max=128000 拦死长上下文)', () => {
    renderTab(vi.fn(), fixedContext);
    const select = screen.getByLabelText('最大上下文长度档位');
    const labels = Array.from((select as HTMLSelectElement).options).map((o) => o.text);
    expect(labels).toEqual(expect.arrayContaining(['512K', '1M', '2M', '自定义…']));
  });

  it('值命中预设档时选中对应档位, 切换档位直接写回归一化 token 数', () => {
    const updateSettings = vi.fn();
    renderTab(updateSettings, { ...fixedContext, maxContext: 131072 });
    const select = screen.getByLabelText('最大上下文长度档位') as HTMLSelectElement;
    expect(select.value).toBe('131072');

    fireEvent.change(select, { target: { value: '524288' } });
    expect(updateSettings).toHaveBeenCalledWith({ maxContext: 524288 });
  });

  it('自定义模式: 数值 + 单位切换按乘数归一化写回', () => {
    // 300000 非预设档 → 直接进自定义形态, 派生初值 300 + K
    const updateSettings = vi.fn();
    renderTab(updateSettings, { ...fixedContext, maxContext: 300000 });
    expect(screen.getByLabelText('上下文长度数值')).toHaveValue(300);

    fireEvent.change(screen.getByLabelText('上下文长度数值'), { target: { value: '512' } });
    expect(updateSettings).toHaveBeenLastCalledWith({ maxContext: 512000 });

    fireEvent.change(screen.getByLabelText('上下文长度数值'), { target: { value: '1' } });
    fireEvent.change(screen.getByLabelText('上下文长度单位'), { target: { value: 'M' } });
    expect(updateSettings).toHaveBeenLastCalledWith({ maxContext: 1000000 });
  });

  it('旧数据非预设值 (8000) 自动进入自定义形态并回显', () => {
    renderTab(vi.fn(), { ...fixedContext, maxContext: 8000 });
    const select = screen.getByLabelText('最大上下文长度档位') as HTMLSelectElement;
    expect(select.value).toBe('custom');
    // 8000 派生为 8 + K 的自定义初值
    expect(screen.getByLabelText('上下文长度数值')).toHaveValue(8);
    expect((screen.getByLabelText('上下文长度单位') as HTMLSelectElement).value).toBe('K');
    expect(screen.getByTestId('settings-context-length-resolved').textContent).toContain('8,000');
  });
});

describe('ModelsTab routing mode (Task 11)', () => {
  const autoSettings = { ...settings, routing: { mode: 'auto' as const } };

  it('defaults to manual mode and renders no read-only routing table', () => {
    renderTab();

    expect(screen.getByTestId('settings-routing-mode-manual')).toBeChecked();
    expect(screen.getByTestId('settings-routing-mode-auto')).not.toBeChecked();
    expect(screen.queryByTestId('settings-routing-table')).toBeNull();
  });

  it('writes routing.mode when the auto radio is selected', () => {
    const updateSettings = vi.fn();
    renderTab(updateSettings);

    fireEvent.click(screen.getByTestId('settings-routing-mode-auto'));

    expect(updateSettings).toHaveBeenCalledWith(
      expect.objectContaining({ routing: expect.objectContaining({ mode: 'auto' }) }),
    );
  });

  it('auto mode shows the mapping table + chat endpoint row and hides the chat picker', () => {
    renderTab(vi.fn(), autoSettings);

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
    // 隐藏 chat 选择器剩 5 个；排除本地 OCR 的引擎/语言下拉与会话标题模型下拉
    //（均非模型能力选择器）。
    // 另加 P0-A 的上下文档位下拉（两种模式都渲染，仅自动模式禁用），故 +1。
    const capabilitySelects = (container: HTMLElement) =>
      container.querySelectorAll(
        'select:not([data-testid^="settings-ocr-"]):not([data-testid="settings-title-model"])',
      );

    const manual = renderTab();
    expect(capabilitySelects(manual.container)).toHaveLength(7);
    manual.unmount();

    const auto = renderTab(vi.fn(), autoSettings);
    expect(capabilitySelects(auto.container)).toHaveLength(6);
  });

  it('keeps the routing switch reachable when no endpoint has models (R31a)', () => {
    const emptySettings = { ...settings, endpoints: [] };
    renderTab(vi.fn(), emptySettings);

    expect(screen.getByTestId('settings-routing-mode-auto')).toBeInTheDocument();
    expect(screen.getByTestId('settings-routing-mode-manual')).toBeChecked();
    expect(screen.getByText(/请先在/)).toBeInTheDocument();
  });
});
