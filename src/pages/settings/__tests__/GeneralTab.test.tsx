// @vitest-environment jsdom
/**
 * GeneralTab — M1 权限模式选择器测试。
 *
 * 只验证 PermissionModeSelector 行为；ThemeSelector / DiagnosticsCard /
 * useSettings 全部桩化（与 ThemeSelector.test.tsx 同思路），避免主题/诊断
 * 子树的 IPC 依赖干扰。
 *
 * 持久化契约: get_preference / set_preference key='permission_mode'
 * （KV 存储 — 后端 SettingsRepository.KEYS 白名单；见 GeneralTab.tsx 注释）。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { DEFAULT_SETTINGS } from '../../../entities/setting/types';
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
  useSettings: () => ({
    settings: DEFAULT_SETTINGS,
    isLoading: false,
    updateSettings: mocks.updateSettings,
    resetSettings: vi.fn(),
  }),
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
  mocks.getPreference.mockReset();
  mocks.setPreference.mockReset();
  mocks.getPreference.mockResolvedValue(null);
  mocks.setPreference.mockResolvedValue(undefined);
});

describe('GeneralTab permission mode selector (M1)', () => {
  it('renders the permission section with 4 mode options', async () => {
    renderTab();

    expect(screen.getByText('工具权限')).toBeInTheDocument();
    const select = screen.getByTestId('permission-mode-select') as HTMLSelectElement;
    const options = Array.from(select.options).map((o) => o.value);
    expect(options).toEqual(['read_only', 'workspace_write', 'prompt', 'full_access']);

    // 后端无值 → 默认 workspace_write（与 DEFAULT_PERMISSION_MODE 一致）
    await waitFor(() => {
      expect(mocks.getPreference).toHaveBeenCalledWith('permission_mode');
    });
    expect(select.value).toBe('workspace_write');
  });

  it('loads persisted mode from get_preference', async () => {
    mocks.getPreference.mockResolvedValue('full_access');
    renderTab();

    const select = screen.getByTestId('permission-mode-select') as HTMLSelectElement;
    await waitFor(() => {
      expect(select.value).toBe('full_access');
    });
  });

  it('falls back to workspace_write on unknown persisted value', async () => {
    mocks.getPreference.mockResolvedValue('not_a_mode');
    renderTab();

    const select = screen.getByTestId('permission-mode-select') as HTMLSelectElement;
    await waitFor(() => {
      expect(mocks.getPreference).toHaveBeenCalled();
    });
    expect(select.value).toBe('workspace_write');
  });

  it('changing the select persists via set_preference(permission_mode)', async () => {
    renderTab();

    const select = screen.getByTestId('permission-mode-select');
    fireEvent.change(select, { target: { value: 'prompt' } });

    expect(mocks.setPreference).toHaveBeenCalledWith('permission_mode', 'prompt', 'permissions');
    expect((select as HTMLSelectElement).value).toBe('prompt');
    // 模式描述文案随选择更新
    expect(screen.getByText('所有写入与执行操作都需要手动批准')).toBeInTheDocument();
  });

  it('shows the JSON-only rules hint', () => {
    renderTab();
    expect(screen.getByText(/permission_rules JSON/)).toBeInTheDocument();
  });
});
