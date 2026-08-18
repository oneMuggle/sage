// @vitest-environment jsdom
/**
 * GeneralTab — Wave 3 P2-9 编排（Orchestration）设置 section 测试。
 *
 * 只验证编排 section 的 5 个数值输入与部分更新契约：
 * updateSettings({ orch: { ...settings.orch, [key]: v } }) 必须保留其余 orch 键。
 * 与 GeneralTab.test.tsx 同思路：useSettings / settingsClient / 子组件桩化。
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { DEFAULT_SETTINGS } from '../../../entities/setting/types';
import { useSettings } from '../../../features/manage-settings/useSettings';
import { I18nProvider } from '../../../shared/lib/i18n';
import { GeneralTab } from '../GeneralTab';

const mocks = vi.hoisted(() => ({
  getPreference: vi.fn(),
  setPreference: vi.fn(),
  updateSettings: vi.fn(),
}));

vi.mock('../../../shared/api/settingsClient', () => ({
  LOAD_TIMEOUT_MS: 5000,
  settingsClient: {
    getSettings: vi.fn().mockResolvedValue(null),
    setSettings: vi.fn().mockResolvedValue(undefined),
    getPreference: (...args: unknown[]) => mocks.getPreference(...args),
    setPreference: (...args: unknown[]) => mocks.setPreference(...args),
  },
}));

vi.mock('../../../features/manage-settings/useSettings', () => ({
  useSettings: vi.fn(() => ({
    settings: { ...DEFAULT_SETTINGS, orch: { ...DEFAULT_SETTINGS.orch } },
    isLoading: false,
    updateSettings: mocks.updateSettings,
    resetSettings: vi.fn(),
  })),
}));

vi.mock('../../../widgets/settings/DiagnosticsCard', () => ({
  DiagnosticsCard: () => <div data-testid="diagnostics-stub" />,
}));

vi.mock('../ThemeSelector', () => ({
  ThemeSelector: () => <div data-testid="theme-selector-stub" />,
}));

function renderTab(): void {
  render(
    <I18nProvider>
      <GeneralTab resetSettings={vi.fn()} />
    </I18nProvider>,
  );
}

beforeEach(() => {
  vi.mocked(useSettings).mockImplementation(() => ({
    settings: { ...DEFAULT_SETTINGS, orch: { ...DEFAULT_SETTINGS.orch } },
    isLoading: false,
    updateSettings: mocks.updateSettings,
    resetSettings: vi.fn(),
  }));
  mocks.updateSettings.mockReset();
  mocks.getPreference.mockReset();
  mocks.setPreference.mockReset();
  mocks.getPreference.mockResolvedValue(null);
  mocks.setPreference.mockResolvedValue(undefined);
});

describe('GeneralTab 编排 section', () => {
  it('渲染 6 个编排数值输入（含子代理迭代上限）', () => {
    renderTab();
    expect(screen.getByTestId('orch-max-concurrent')).toBeInTheDocument();
    expect(screen.getByTestId('orch-max-aggregate')).toBeInTheDocument();
    expect(screen.getByTestId('orch-max-subagent-result')).toBeInTheDocument();
    expect(screen.getByTestId('orch-max-retries')).toBeInTheDocument();
    expect(screen.getByTestId('orch-max-lane-iterations')).toBeInTheDocument();
    expect(screen.getByTestId('orch-max-subagent-iterations')).toBeInTheDocument();
  });

  it('子代理迭代上限默认 6，修改后 updateSettings 保留其它键', () => {
    const updateSettings = vi.fn();
    vi.mocked(useSettings).mockReturnValue({
      settings: { ...DEFAULT_SETTINGS, orch: { ...DEFAULT_SETTINGS.orch } },
      isLoading: false,
      updateSettings,
      resetSettings: vi.fn(),
    });
    renderTab();

    // 默认 6 (与 backend OrchSettings.max_subagent_iterations 默认对齐)
    const subagentInput = screen.getByTestId('orch-max-subagent-iterations') as HTMLInputElement;
    expect(subagentInput.value).toBe('6');

    fireEvent.change(subagentInput, { target: { value: '12' } });
    expect(updateSettings).toHaveBeenCalledWith({
      orch: expect.objectContaining({
        maxSubagentIterations: 12,
        maxLaneIterations: 8, // 保留其余键（部分更新契约）
        maxRetries: 2,
      }),
    });
  });

  it('修改数值调 updateSettings 且保留其余 orch 键', () => {
    const updateSettings = vi.fn();
    vi.mocked(useSettings).mockReturnValue({
      settings: { ...DEFAULT_SETTINGS, orch: { ...DEFAULT_SETTINGS.orch, maxRetries: 2 } },
      isLoading: false,
      updateSettings,
      resetSettings: vi.fn(),
    });
    renderTab();

    fireEvent.change(screen.getByTestId('orch-max-retries'), { target: { value: '5' } });
    expect(updateSettings).toHaveBeenCalledWith({
      orch: expect.objectContaining({ maxRetries: 5, maxConcurrentSubagents: 4 }),
    });
  });

  it('清空输入不提交 0 — 防 Semaphore(0) 编排挂死', () => {
    renderTab();

    fireEvent.change(screen.getByTestId('orch-max-concurrent'), { target: { value: '' } });
    expect(mocks.updateSettings).not.toHaveBeenCalled();

    fireEvent.change(screen.getByTestId('orch-max-aggregate'), { target: { value: '' } });
    expect(mocks.updateSettings).not.toHaveBeenCalled();
  });
});
