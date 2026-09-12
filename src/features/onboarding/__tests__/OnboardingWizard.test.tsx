/**
 * R26: 首启配置向导测试
 *
 * - 无可用端点时 Welcome 展示向导；已配置/手动关闭后不展示
 * - 三步流: 协议 → 地址密钥 → openai 测试连接选模型保存
 * - 非 openai 协议跳过测试直接保存
 * - updateSettings 写入 endpoints + chatModel 选择
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const testConnectionMock = vi.fn();
const updateSettingsMock = vi.fn();

vi.mock('../../manage-endpoints/api', async () => {
  const actual = await vi.importActual<typeof import('../../manage-endpoints/api')>(
    '../../manage-endpoints/api',
  );
  return {
    ...actual,
    testEndpointConnection: (...args: unknown[]) => testConnectionMock(...args),
  };
});

vi.mock('../../manage-settings/useSettings', () => ({
  useSettings: () => ({
    settings: {
      endpoints: currentEndpoints,
      modelSelections: {
        chatModel: { endpointId: null, modelId: null },
        visionModel: { endpointId: null, modelId: null },
        embeddingModel: { endpointId: null, modelId: null },
        ttsModel: { endpointId: null, modelId: null },
        asrModel: { endpointId: null, modelId: null },
        imageGenModel: { endpointId: null, modelId: null },
      },
    },
    isLoading: false,
    updateSettings: updateSettingsMock,
    loadSettings: vi.fn(),
    resetSettings: vi.fn(),
  }),
}));

import { I18nProvider } from '../../../shared/lib/i18n';
import { OnboardingWizard } from '../OnboardingWizard';

let currentEndpoints: { baseUrl: string; apiKey: string; protocol: string }[] = [];

const renderWizard = () =>
  render(
    <I18nProvider defaultLocale="zh">
      <OnboardingWizard onComplete={vi.fn()} />
    </I18nProvider>,
  );

describe('OnboardingWizard — R26', () => {
  beforeEach(() => {
    currentEndpoints = [];
    testConnectionMock.mockReset();
    updateSettingsMock.mockReset();
    updateSettingsMock.mockResolvedValue(undefined);
  });

  it('默认展示协议选择（第一步）', () => {
    renderWizard();
    expect(screen.getByTestId('wizard-step-protocol')).toBeInTheDocument();
  });

  it('协议选 openai → 填地址密钥 → 测试成功 → 选模型保存', async () => {
    testConnectionMock.mockResolvedValue({
      success: true,
      message: '发现 3 个模型',
      latency: 12,
      discoveredModels: [{ id: 'gpt-x' }, { id: 'gpt-y' }, { id: 'text-embed' }],
    });
    renderWizard();

    // 第一步默认 openai-compatible，直接下一步
    fireEvent.click(screen.getByTestId('wizard-next-0'));
    expect(screen.getByTestId('wizard-step-credentials')).toBeInTheDocument();

    fireEvent.change(screen.getByTestId('wizard-baseurl'), {
      target: { value: 'https://api.example.com/v1' },
    });
    fireEvent.change(screen.getByTestId('wizard-apikey'), { target: { value: 'sk-1' } });
    fireEvent.click(screen.getByTestId('wizard-next-1'));

    expect(screen.getByTestId('wizard-step-test')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('wizard-test'));
    await waitFor(() => expect(testConnectionMock).toHaveBeenCalled());
    expect(screen.getByTestId('wizard-test-result')).toHaveTextContent('发现 3 个模型');

    fireEvent.change(screen.getByTestId('wizard-model'), { target: { value: 'gpt-x' } });
    fireEvent.click(screen.getByTestId('wizard-save'));

    await waitFor(() => expect(screen.getByTestId('wizard-finish')).toBeInTheDocument());
    expect(updateSettingsMock).toHaveBeenCalledTimes(1);
    const patch = updateSettingsMock.mock.calls[0][0];
    expect(patch.endpoints).toHaveLength(1);
    expect(patch.endpoints[0].baseUrl).toBe('https://api.example.com/v1');
    expect(patch.endpoints[0].modelId).toBe('gpt-x');
    expect(patch.modelSelections.chatModel).toEqual({
      endpointId: patch.endpoints[0].id,
      modelId: 'gpt-x',
    });
  });

  it('ollama 协议跳过密钥与测试，直接保存', async () => {
    renderWizard();
    // 选 Ollama（第 4 个协议卡）
    fireEvent.click(screen.getByText('Ollama（本地）'));
    fireEvent.click(screen.getByTestId('wizard-next-0'));
    // 无密钥输入框
    expect(screen.queryByTestId('wizard-apikey')).not.toBeInTheDocument();
    fireEvent.change(screen.getByTestId('wizard-baseurl'), {
      target: { value: 'http://localhost:11434' },
    });
    // 按钮文案是"直接保存"，点击后直接进入保存步（无测试按钮）
    fireEvent.click(screen.getByTestId('wizard-next-1'));
    expect(screen.queryByTestId('wizard-test')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('wizard-save'));

    await waitFor(() => expect(updateSettingsMock).toHaveBeenCalled());
    const patch = updateSettingsMock.mock.calls[0][0];
    expect(patch.endpoints[0].protocol).toBe('ollama');
  });

  it('测试失败展示错误信息，仍可保存', async () => {
    testConnectionMock.mockResolvedValue({
      success: false,
      message: '连接被拒绝',
      latency: 5,
    });
    renderWizard();
    fireEvent.click(screen.getByTestId('wizard-next-0'));
    fireEvent.change(screen.getByTestId('wizard-baseurl'), {
      target: { value: 'https://bad.example.com' },
    });
    fireEvent.change(screen.getByTestId('wizard-apikey'), { target: { value: 'k' } });
    fireEvent.click(screen.getByTestId('wizard-next-1'));
    fireEvent.click(screen.getByTestId('wizard-test'));
    await waitFor(() =>
      expect(screen.getByTestId('wizard-test-result')).toHaveTextContent('连接被拒绝'),
    );
    fireEvent.click(screen.getByTestId('wizard-save'));
    await waitFor(() => expect(updateSettingsMock).toHaveBeenCalled());
  });

  it('跳过按钮不写入任何设置', () => {
    renderWizard();
    fireEvent.click(screen.getByTestId('wizard-skip'));
    expect(updateSettingsMock).not.toHaveBeenCalled();
  });
});
