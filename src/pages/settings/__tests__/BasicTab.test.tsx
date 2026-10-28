// @vitest-environment jsdom
/**
 * BasicTab 单元测试 — LLM 重试设置 section
 *
 * 测试范围：
 * 1. LLM 重试 section 渲染（默认值、输入控件、data-testid）
 * 2. 输入变更触发 updateSettings
 * 3. AdvancedSection 折叠/展开交互
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { FontProvider } from '../../../entities/font/useFontSettings';
import { DEFAULT_SETTINGS } from '../../../entities/setting/types';
import { I18nProvider } from '../../../shared/lib/i18n';
import { BasicTab, formatBasicTabAuditJson, formatBasicTabAuditSnapshot } from '../BasicTab';

// ==================== Mocks ====================

const mocks = vi.hoisted(() => ({
  updateSettings: vi.fn(),
  setSettings: vi.fn(),
}));

vi.mock('../../../shared/api/settingsClient', () => ({
  LOAD_TIMEOUT_MS: 5000,
  settingsClient: {
    getSettings: vi.fn().mockResolvedValue(null),
    setSettings: (...args: unknown[]) => mocks.setSettings(...args),
    getPreference: vi.fn().mockResolvedValue(null),
    setPreference: vi.fn().mockResolvedValue(undefined),
    getContextTurnLimit: vi.fn().mockResolvedValue(null),
    setContextTurnLimit: vi.fn().mockResolvedValue(undefined),
  },
}));

vi.mock('../../../features/manage-settings/useSettings', () => ({
  useSettings: () => ({
    settings: DEFAULT_SETTINGS,
    isLoading: false,
    updateSettings: mocks.updateSettings,
    resetSettings: vi.fn(),
  }),
}));

vi.mock('../ThemeSelector', () => ({
  ThemeSelector: () => <div data-testid="theme-selector-stub" />,
}));

vi.mock('../../../entities/font/fontStorage', () => ({
  loadFontSettings: async () => ({
    fontUi: 'inter',
    fontCode: 'jetbrains-mono',
    fontSizeUi: 14,
    fontSizeCode: 13,
  }),
  saveFontSettings: async () => undefined,
}));

function renderTab(): void {
  render(
    <I18nProvider>
      <FontProvider>
        <BasicTab />
      </FontProvider>
    </I18nProvider>,
  );
}

beforeEach(() => {
  mocks.updateSettings.mockClear();
  mocks.setSettings.mockClear();
});

describe('BasicTab — LLM 重试 section', () => {
  it('渲染 LLM 重试 section 及默认值', () => {
    renderTab();

    // section 标题
    expect(screen.getByText('LLM 重试')).toBeTruthy();

    // 最大重试次数 input 存在且默认值为 3
    const maxAttemptsInput = screen.getByTestId('settings-llm-retry-max-attempts');
    expect(maxAttemptsInput).toBeTruthy();
    expect((maxAttemptsInput as HTMLInputElement).value).toBe('3');

    // 描述文本
    expect(screen.getByText(/LLM 请求失败后自动重试的次数上限/)).toBeTruthy();
  });

  it('修改最大重试次数触发 updateSettings', async () => {
    renderTab();

    const input = screen.getByTestId('settings-llm-retry-max-attempts');
    fireEvent.change(input, { target: { value: '5' } });

    await waitFor(() => {
      expect(mocks.updateSettings).toHaveBeenCalledWith({ llmRetryMaxAttempts: 5 });
    });
  });

  it('设为 0 表示禁用重试', async () => {
    renderTab();

    const input = screen.getByTestId('settings-llm-retry-max-attempts');
    fireEvent.change(input, { target: { value: '0' } });

    await waitFor(() => {
      expect(mocks.updateSettings).toHaveBeenCalledWith({ llmRetryMaxAttempts: 0 });
    });
  });

  it('输入超过 10 被 clamp 到 10', async () => {
    renderTab();

    const input = screen.getByTestId('settings-llm-retry-max-attempts');
    fireEvent.change(input, { target: { value: '99' } });

    await waitFor(() => {
      expect(mocks.updateSettings).toHaveBeenCalledWith({ llmRetryMaxAttempts: 10 });
    });
  });

  it('输入负数被 clamp 到 0', async () => {
    renderTab();

    const input = screen.getByTestId('settings-llm-retry-max-attempts');
    fireEvent.change(input, { target: { value: '-5' } });

    await waitFor(() => {
      expect(mocks.updateSettings).toHaveBeenCalledWith({ llmRetryMaxAttempts: 0 });
    });
  });

  it('AdvancedSection 默认折叠，高级参数不可见', () => {
    renderTab();

    // "高级选项" 按钮存在
    const advancedButton = screen.getByText('高级选项');
    expect(advancedButton).toBeTruthy();

    // 折叠状态下，退避基数/最大退避 input 在 DOM 中但 hidden
    const baseDelayInput = screen.queryByTestId('settings-llm-retry-base-delay');
    const maxDelayInput = screen.queryByTestId('settings-llm-retry-max-delay');

    // hidden 元素仍在 DOM 中但被 [hidden] 祖先包裹
    if (baseDelayInput) {
      expect(baseDelayInput.closest('[hidden]')).toBeTruthy();
    }
    if (maxDelayInput) {
      expect(maxDelayInput.closest('[hidden]')).toBeTruthy();
    }
  });

  it('点击"高级选项"展开后，退避参数可见', async () => {
    renderTab();

    const advancedButton = screen.getByText('高级选项');
    fireEvent.click(advancedButton);

    await waitFor(() => {
      // 展开后 hidden 属性移除
      const baseDelayInput = screen.getByTestId('settings-llm-retry-base-delay');
      const maxDelayInput = screen.getByTestId('settings-llm-retry-max-delay');
      expect(baseDelayInput).toBeTruthy();
      expect(maxDelayInput).toBeTruthy();
      expect((baseDelayInput as HTMLInputElement).value).toBe('1');
      expect((maxDelayInput as HTMLInputElement).value).toBe('30');
    });
  });

  it('展开后修改退避基数触发 updateSettings', async () => {
    renderTab();

    // 先展开
    fireEvent.click(screen.getByText('高级选项'));

    const baseDelayInput = screen.getByTestId('settings-llm-retry-base-delay');
    fireEvent.change(baseDelayInput, { target: { value: '2.5' } });

    await waitFor(() => {
      expect(mocks.updateSettings).toHaveBeenCalledWith({ llmRetryBaseDelayS: 2.5 });
    });
  });

  it('展开后修改最大退避触发 updateSettings', async () => {
    renderTab();

    // 先展开
    fireEvent.click(screen.getByText('高级选项'));

    const maxDelayInput = screen.getByTestId('settings-llm-retry-max-delay');
    fireEvent.change(maxDelayInput, { target: { value: '60' } });

    await waitFor(() => {
      expect(mocks.updateSettings).toHaveBeenCalledWith({ llmRetryMaxDelayS: 60 });
    });
  });

  it('exports BasicTab audit snapshot and JSON helpers and renders copy controls', () => {
    renderTab();
    expect(screen.getByTestId('basic-tab-copy-audit')).toBeTruthy();

    const snapshot = formatBasicTabAuditSnapshot({
      streaming: true,
      llmRetryMaxAttempts: 3,
      llmRetryBaseDelayS: 1,
      llmRetryMaxDelayS: 30,
      llmTotalTimeoutS: 1800,
      llmProxyTimeoutS: 60,
      timezone: 'Asia/Shanghai',
      logTimezone: 'UTC',
      demoMode: false,
    });
    expect(snapshot).toContain('# 基础设置审计快照');
    expect(snapshot).toContain('流式输出: 开启');
    expect(snapshot).toContain('IANA 时区: Asia/Shanghai');
    expect(snapshot).toContain('LLM 任务上限(秒): 1800');

    const json = JSON.parse(
      formatBasicTabAuditJson({
        streaming: false,
        llmRetryMaxAttempts: 0,
        llmRetryBaseDelayS: 2,
        llmRetryMaxDelayS: 60,
        llmTotalTimeoutS: 0,
        llmProxyTimeoutS: 300,
        timezone: '',
        logTimezone: '',
        demoMode: true,
      }),
    );
    expect(json).toEqual({
      streaming: false,
      llmRetryMaxAttempts: 0,
      llmRetryBaseDelayS: 2,
      llmRetryMaxDelayS: 60,
      llmTotalTimeoutS: 0,
      llmProxyTimeoutS: 300,
      timezone: 'Asia/Shanghai',
      logTimezone: 'UTC',
      demoMode: true,
    });
  });
});

describe('BasicTab — LLM 任务上限 section', () => {
  it('渲染「LLM 任务上限」区块及默认 1800 秒', () => {
    renderTab();

    expect(screen.getByText('LLM 任务上限')).toBeTruthy();

    const input = screen.getByTestId('settings-llm-total-timeout');
    expect(input).toBeTruthy();
    expect((input as HTMLInputElement).value).toBe('1800');

    // 描述必须点明 0 = 不限 + 环境变量优先级，避免用户误以为是网络超时
    expect(screen.getByText(/0 = 不限上限/)).toBeTruthy();
    expect(screen.getByText(/SAGE_LLM_TOTAL_TIMEOUT_S/)).toBeTruthy();
  });

  it('修改总耗时上限触发 updateSettings', async () => {
    renderTab();

    const input = screen.getByTestId('settings-llm-total-timeout');
    fireEvent.change(input, { target: { value: '3600' } });

    await waitFor(() => {
      expect(mocks.updateSettings).toHaveBeenCalledWith({ llmTotalTimeoutS: 3600 });
    });
  });

  it('设为 0 表示不限上限', async () => {
    renderTab();

    const input = screen.getByTestId('settings-llm-total-timeout');
    fireEvent.change(input, { target: { value: '0' } });

    await waitFor(() => {
      expect(mocks.updateSettings).toHaveBeenCalledWith({ llmTotalTimeoutS: 0 });
    });
  });

  it('输入负数被 clamp 到 0', async () => {
    renderTab();

    const input = screen.getByTestId('settings-llm-total-timeout');
    fireEvent.change(input, { target: { value: '-30' } });

    await waitFor(() => {
      expect(mocks.updateSettings).toHaveBeenCalledWith({ llmTotalTimeoutS: 0 });
    });
  });

  it('审计快照把 0 渲染成「不限」', () => {
    const snapshot = formatBasicTabAuditSnapshot({
      streaming: true,
      llmRetryMaxAttempts: 3,
      llmRetryBaseDelayS: 1,
      llmRetryMaxDelayS: 30,
      llmTotalTimeoutS: 0,
      llmProxyTimeoutS: 300,
      timezone: 'Asia/Shanghai',
      logTimezone: 'UTC',
      demoMode: false,
    });
    expect(snapshot).toContain('LLM 任务上限(秒): 不限');
  });
});

describe('BasicTab — LLM 代理超时 section', () => {
  it('渲染默认 60 秒并说明 read 超时语义', () => {
    renderTab();

    expect(screen.getByText('LLM 代理超时')).toBeTruthy();

    const input = screen.getByTestId('settings-llm-proxy-timeout');
    expect((input as HTMLInputElement).value).toBe('60');

    // 说明必须点明「两次收到字节之间的间隔」语义，否则用户会当成整段生成耗时
    expect(screen.getByText(/两次收到字节之间的最大等待时间/)).toBeTruthy();
  });

  it('修改超时后失焦触发 updateSettings', async () => {
    renderTab();

    const input = screen.getByTestId('settings-llm-proxy-timeout');
    fireEvent.change(input, { target: { value: '300' } });

    // 输入过程中不提交：逐键 clamp 会把 "3" 改成 5，最终得到 500 而非 300
    expect((input as HTMLInputElement).value).toBe('300');
    expect(mocks.updateSettings).not.toHaveBeenCalled();

    fireEvent.blur(input);
    await waitFor(() => {
      expect(mocks.updateSettings).toHaveBeenCalledWith({ llmProxyTimeoutS: 300 });
    });
  });

  it('越界输入在失焦时被 clamp 到 5–1800', async () => {
    renderTab();

    const input = screen.getByTestId('settings-llm-proxy-timeout');
    fireEvent.change(input, { target: { value: '99999' } });
    fireEvent.blur(input);
    await waitFor(() => {
      expect(mocks.updateSettings).toHaveBeenCalledWith({ llmProxyTimeoutS: 1800 });
    });

    fireEvent.change(input, { target: { value: '1' } });
    fireEvent.blur(input);
    await waitFor(() => {
      expect(mocks.updateSettings).toHaveBeenCalledWith({ llmProxyTimeoutS: 5 });
    });
  });
});
