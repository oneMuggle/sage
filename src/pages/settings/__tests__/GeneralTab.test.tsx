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

import { FontProvider } from '../../../entities/font/useFontSettings';
import { DEFAULT_SETTINGS } from '../../../entities/setting/types';
import { I18nProvider } from '../../../shared/lib/i18n';
import {
  GeneralTab,
  formatGeneralTabAuditJson,
  formatGeneralTabAuditSnapshot,
} from '../GeneralTab';

const mocks = vi.hoisted(() => ({
  getPreference: vi.fn(),
  setPreference: vi.fn(),
  updateSettings: vi.fn(),
  listRules: vi.fn(),
  deleteRule: vi.fn(),
  clearRules: vi.fn(),
  confirmDialog: vi.fn(),
}));

vi.mock('../../../shared/api/settingsClient', () => ({
  LOAD_TIMEOUT_MS: 5000,
  settingsClient: {
    getSettings: vi.fn().mockResolvedValue(null),
    setSettings: vi.fn().mockResolvedValue(undefined),
    getPreference: (...args: unknown[]) => mocks.getPreference(...args),
    setPreference: (...args: unknown[]) => mocks.setPreference(...args),
    getContextTurnLimit: vi.fn().mockResolvedValue(null),
    setContextTurnLimit: vi.fn().mockResolvedValue(undefined),
  },
}));

vi.mock('../../../shared/api/permissionApi', () => ({
  permissionApi: {
    getPreset: vi.fn().mockResolvedValue({
      preset: 'standard',
      mode: 'workspace_write',
      custom: false,
    }),
    setPreset: vi.fn().mockResolvedValue(undefined),
    getSessionAutoApprovals: vi
      .fn()
      .mockResolvedValue({ session_id: '', count: 0, total: 0, items: [] }),
    getTrustPolicy: vi.fn().mockResolvedValue({
      enabled: false,
      threshold: 3,
      default_threshold: 3,
      consecutive: {},
    }),
    setTrustPolicy: vi.fn().mockResolvedValue({
      enabled: false,
      threshold: 3,
      default_threshold: 3,
      consecutive: {},
    }),
    listRules: (...args: unknown[]) => mocks.listRules(...args),
    deleteRule: (...args: unknown[]) => mocks.deleteRule(...args),
    clearRules: (...args: unknown[]) => mocks.clearRules(...args),
  },
}));

vi.mock('../../../shared/ui/ConfirmDialog/confirmService', () => ({
  confirmDialog: (...args: unknown[]) => mocks.confirmDialog(...args),
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

vi.mock('../../../entities/font/fontStorage', () => ({
  loadFontSettings: async () => ({
    fontUi: 'inter',
    fontCode: 'jetbrains-mono',
    fontSizeUi: 14,
    fontSizeCode: 13,
  }),
  saveFontSettings: async () => undefined,
}));

function renderTab(resetSettings = vi.fn()): void {
  render(
    <I18nProvider>
      <FontProvider>
        <GeneralTab resetSettings={resetSettings} />
      </FontProvider>
    </I18nProvider>,
  );
}

beforeEach(() => {
  mocks.getPreference.mockReset();
  mocks.setPreference.mockReset();
  mocks.getPreference.mockResolvedValue(null);
  mocks.setPreference.mockResolvedValue(undefined);
  mocks.listRules.mockReset();
  mocks.deleteRule.mockReset();
  mocks.clearRules.mockReset();
  mocks.confirmDialog.mockReset();
  mocks.listRules.mockResolvedValue([]);
  mocks.deleteRule.mockResolvedValue([]);
  mocks.clearRules.mockResolvedValue([]);
  mocks.confirmDialog.mockResolvedValue(true);
});

describe('GeneralTab font controls', () => {
  it('labels controls, enforces integer bounds and updates UI/code independently', async () => {
    renderTab();
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '恢复默认字体' })).not.toBeDisabled();
    });
    const ui = screen.getByRole('combobox', { name: '界面字体' });
    const code = screen.getByRole('combobox', { name: '代码字体' });
    expect(ui).toHaveValue('inter');
    expect(code).toHaveValue('jetbrains-mono');
    const size = screen.getByRole('spinbutton', { name: '界面字号' });
    const slider = screen.getByRole('slider', { name: '代码字号' });
    expect(size).toHaveAttribute('min', '10');
    expect(size).toHaveAttribute('max', '24');
    expect(size).toHaveAttribute('step', '1');
    expect(slider).toHaveAttribute('step', '1');
    fireEvent.change(size, { target: { value: '20' } });
    await waitFor(() =>
      expect(document.documentElement.style.getPropertyValue('--font-size-ui')).toBe('20px'),
    );
    expect(document.documentElement.style.getPropertyValue('--font-size-code')).toBe('13px');
    fireEvent.change(slider, { target: { value: '24' } });
    await waitFor(() =>
      expect(screen.getByRole('spinbutton', { name: '代码字号' })).toHaveValue(24),
    );
    fireEvent.change(ui, { target: { value: 'system' } });
    await waitFor(() =>
      expect(document.documentElement.style.getPropertyValue('--font-ui')).toContain('system-ui'),
    );
    fireEvent.change(code, { target: { value: 'consolas' } });
    await waitFor(() =>
      expect(document.documentElement.style.getPropertyValue('--font-code')).toContain('Consolas'),
    );
    fireEvent.click(screen.getByRole('button', { name: '恢复默认字体' }));
    await waitFor(() => {
      expect(screen.getByRole('spinbutton', { name: '界面字号' })).toHaveValue(14);
      expect(screen.getByRole('slider', { name: '代码字号' })).toHaveValue('13');
      expect(screen.getByRole('combobox', { name: '界面字体' })).toHaveValue('inter');
    });
    expect(screen.getByText(/未安装的字体会自动回退/)).toBeInTheDocument();
  });
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

  it('shows the remembered-rules hint and empty state', async () => {
    renderTab();
    expect(screen.getByText(/已记住的规则可在下方查看并逐条删除/)).toBeInTheDocument();
    expect(screen.getByText('已记住的规则')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText('暂无已记住的规则')).toBeInTheDocument();
    });
  });
});

describe('GeneralTab remembered rules manager (R97)', () => {
  it('renders saved rules with decision labels', async () => {
    mocks.listRules.mockResolvedValue([
      { tool_pattern: 'bash', decision: 'deny' },
      { tool_pattern: 'plugin__demo__*', decision: 'allow' },
    ]);
    renderTab();

    await waitFor(() => {
      expect(screen.getByText('bash')).toBeInTheDocument();
    });
    expect(screen.getByText('plugin__demo__*')).toBeInTheDocument();
    expect(screen.getByText('拒绝')).toBeInTheDocument();
    expect(screen.getByText('允许')).toBeInTheDocument();
    expect(screen.getByTestId('permission-rule-delete-0')).toBeInTheDocument();
    expect(screen.getByTestId('permission-rule-delete-1')).toBeInTheDocument();
  });

  it('badges rules whose plugin was uninstalled or has no record', async () => {
    mocks.listRules.mockResolvedValue([
      {
        tool_pattern: 'plugin__demo__*',
        decision: 'deny',
        plugin_name: 'demo',
        plugin_status: 'uninstalled',
      },
      {
        tool_pattern: 'plugin__ghost__*',
        decision: 'ask',
        plugin_name: null,
        plugin_status: 'missing',
      },
      {
        tool_pattern: 'plugin__live__*',
        decision: 'allow',
        plugin_name: 'live',
        plugin_status: 'enabled',
      },
      { tool_pattern: 'bash', decision: 'allow', plugin_name: null, plugin_status: null },
    ]);
    renderTab();

    await waitFor(() => {
      expect(screen.getByTestId('permission-rule-plugin-status-0')).toHaveTextContent(
        '插件已卸载',
      );
    });
    expect(screen.getByTestId('permission-rule-plugin-status-1')).toHaveTextContent(
      '插件无记录',
    );
    expect(screen.queryByTestId('permission-rule-plugin-status-2')).not.toBeInTheDocument();
    expect(screen.queryByTestId('permission-rule-plugin-status-3')).not.toBeInTheDocument();
  });

  it('deletes a rule and adopts the server-returned list', async () => {
    mocks.listRules.mockResolvedValue([
      { tool_pattern: 'bash', decision: 'deny' },
      { tool_pattern: 'write_file', decision: 'ask' },
    ]);
    mocks.deleteRule.mockResolvedValue([{ tool_pattern: 'write_file', decision: 'ask' }]);
    renderTab();

    await waitFor(() => {
      expect(screen.getByText('bash')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId('permission-rule-delete-0'));

    await waitFor(() => {
      expect(mocks.deleteRule).toHaveBeenCalledWith({ tool_pattern: 'bash', decision: 'deny' });
    });
    await waitFor(() => {
      expect(screen.queryByText('bash')).not.toBeInTheDocument();
    });
    expect(screen.getByText('write_file')).toBeInTheDocument();
  });

  it('shows a load failure message when listing rules fails', async () => {
    mocks.listRules.mockRejectedValue(new Error('backend down'));
    renderTab();

    await waitFor(() => {
      expect(screen.getByTestId('permission-rules-load-failed')).toHaveTextContent(
        '读取已记住规则失败',
      );
    });
  });

  it('keeps the list and shows an error when delete fails', async () => {
    mocks.listRules.mockResolvedValue([{ tool_pattern: 'bash', decision: 'deny' }]);
    mocks.deleteRule.mockRejectedValue(new Error('backend down'));
    renderTab();

    await waitFor(() => {
      expect(screen.getByText('bash')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId('permission-rule-delete-0'));

    await waitFor(() => {
      expect(screen.getByTestId('permission-rules-delete-failed')).toHaveTextContent(
        '删除规则失败',
      );
    });
    expect(screen.getByText('bash')).toBeInTheDocument();
  });

  it('hides the clear-all button when there are no rules', async () => {
    renderTab();

    await waitFor(() => {
      expect(screen.getByText('暂无已记住的规则')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('permission-rules-clear')).not.toBeInTheDocument();
  });

  it('clears all rules after confirmation and adopts the server list', async () => {
    mocks.listRules.mockResolvedValue([
      { tool_pattern: 'bash', decision: 'deny' },
      { tool_pattern: 'write_file', decision: 'ask' },
    ]);
    mocks.clearRules.mockResolvedValue([]);
    renderTab();

    await waitFor(() => {
      expect(screen.getByText('bash')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId('permission-rules-clear'));

    await waitFor(() => {
      expect(mocks.confirmDialog).toHaveBeenCalledWith(
        expect.objectContaining({ danger: true }),
      );
      expect(mocks.clearRules).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(screen.getByText('暂无已记住的规则')).toBeInTheDocument();
    });
    expect(screen.queryByText('bash')).not.toBeInTheDocument();
  });

  it('does not clear when the confirmation is cancelled', async () => {
    mocks.listRules.mockResolvedValue([{ tool_pattern: 'bash', decision: 'deny' }]);
    mocks.confirmDialog.mockResolvedValue(false);
    renderTab();

    await waitFor(() => {
      expect(screen.getByText('bash')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId('permission-rules-clear'));

    await waitFor(() => {
      expect(mocks.confirmDialog).toHaveBeenCalled();
    });
    expect(mocks.clearRules).not.toHaveBeenCalled();
    expect(screen.getByText('bash')).toBeInTheDocument();
  });

  it('keeps the list and shows an error when clearing fails', async () => {
    mocks.listRules.mockResolvedValue([{ tool_pattern: 'bash', decision: 'deny' }]);
    mocks.clearRules.mockRejectedValue(new Error('backend down'));
    renderTab();

    await waitFor(() => {
      expect(screen.getByText('bash')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId('permission-rules-clear'));

    await waitFor(() => {
      expect(screen.getByTestId('permission-rules-clear-failed')).toHaveTextContent(
        '全部删除失败',
      );
    });
    expect(screen.getByText('bash')).toBeInTheDocument();
  });
});

describe('GeneralTab demo mode', () => {
  beforeEach(() => {
    delete (window as unknown as { electronAPI?: unknown }).electronAPI;
    mocks.updateSettings.mockReset();
    mocks.updateSettings.mockResolvedValue(undefined);
  });

  it('persists a successful demo mode toggle through settings and Electron IPC', async () => {
    const setDemoMode = vi.fn().mockResolvedValue({ ok: true });
    (window as unknown as { electronAPI: { setDemoMode: typeof setDemoMode } }).electronAPI = {
      setDemoMode,
    };
    renderTab();

    const toggle = screen.getByTestId('demo-mode-section').querySelector('button')!;
    fireEvent.click(toggle);

    await waitFor(() => expect(mocks.updateSettings).toHaveBeenCalledWith({ demoMode: true }));
    expect(setDemoMode).toHaveBeenCalledWith(true);
  });

  it('rolls back and shows a stable error when IPC persistence fails', async () => {
    const setDemoMode = vi.fn().mockResolvedValue({ ok: false, error: 'absolute/path' });
    (window as unknown as { electronAPI: { setDemoMode: typeof setDemoMode } }).electronAPI = {
      setDemoMode,
    };
    renderTab();

    fireEvent.click(screen.getByTestId('demo-mode-section').querySelector('button')!);

    await waitFor(() =>
      expect(screen.getByTestId('demo-mode-error')).toHaveTextContent('无法保存演示模式设置'),
    );
    expect(screen.getByTestId('demo-mode-error')).not.toHaveTextContent('absolute/path');
    expect(mocks.updateSettings).toHaveBeenNthCalledWith(1, { demoMode: true });
    expect(mocks.updateSettings).toHaveBeenNthCalledWith(2, { demoMode: false });
  });

  it('handles updateSettings rejection and clears the persistence state', async () => {
    mocks.updateSettings.mockRejectedValue(new Error('storage unavailable'));
    renderTab();

    fireEvent.click(screen.getByTestId('demo-mode-section').querySelector('button')!);

    await waitFor(() =>
      expect(screen.getByTestId('demo-mode-error')).toHaveTextContent('storage unavailable'),
    );
    expect(screen.queryByText('正在保存…')).toBeNull();
  });
});

describe('GeneralTab reset-to-defaults confirmation', () => {
  it('requires explicit confirmation before resetting', async () => {
    const resetSettings = vi.fn().mockResolvedValue(undefined);
    renderTab(resetSettings);

    fireEvent.click(screen.getByTestId('settings-reset-button'));
    expect(screen.getByTestId('settings-reset-confirm')).toBeInTheDocument();
    expect(resetSettings).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId('settings-reset-confirm-no'));
    expect(screen.queryByTestId('settings-reset-confirm')).toBeNull();
    expect(resetSettings).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId('settings-reset-button'));
    fireEvent.click(screen.getByTestId('settings-reset-confirm-yes'));
    await waitFor(() => expect(resetSettings).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId('settings-reset-done')).toBeInTheDocument();
  });

  it('surfaces a failure instead of claiming success', async () => {
    const resetSettings = vi.fn().mockRejectedValue(new Error('backend down'));
    renderTab(resetSettings);

    fireEvent.click(screen.getByTestId('settings-reset-button'));
    fireEvent.click(screen.getByTestId('settings-reset-confirm-yes'));

    await waitFor(() => expect(screen.getByTestId('settings-reset-error')).toBeInTheDocument());
    expect(screen.queryByTestId('settings-reset-done')).toBeNull();
  });
});

describe('GeneralTab auto checkpoint (B-2, 默认开)', () => {
  const toggle = () =>
    screen.getByTestId('auto-checkpoint-section').querySelector('button') as HTMLButtonElement;

  it('missing preference = on (safe-by-default)', async () => {
    renderTab();
    await waitFor(() => {
      expect(mocks.getPreference).toHaveBeenCalledWith('auto_checkpoint');
    });
    await waitFor(() => {
      expect(toggle().className).toContain('bg-primary');
    });
  });

  it('explicit "0" stays off', async () => {
    mocks.getPreference.mockImplementation(async (key: string) =>
      key === 'auto_checkpoint' ? '0' : null,
    );
    renderTab();
    await waitFor(() => {
      expect(toggle().className).toContain('bg-line-strong');
    });
  });

  it('formats and copies general tab audit snapshot and JSON', () => {
    expect(
      formatGeneralTabAuditSnapshot({
        streaming: true,
        timezone: 'Asia/Shanghai',
        logTimezone: 'UTC',
        autoMemory: true,
        confirmDelete: false,
      }),
    ).toBe('通用设置 · 流式:开 · 时区:Asia/Shanghai · 日志:UTC · 自动记忆:开 · 删前确认:关');
    expect(
      JSON.parse(
        formatGeneralTabAuditJson({
          streaming: false,
          timezone: ' ',
          logTimezone: ' ',
          autoMemory: false,
          confirmDelete: true,
        }),
      ),
    ).toEqual({
      streaming: false,
      timezone: 'Asia/Shanghai',
      logTimezone: 'UTC',
      autoMemory: false,
      confirmDelete: true,
    });

    renderTab();
    const summaryBtn = screen.getByTestId('general-tab-copy-summary');
    const jsonBtn = screen.getByTestId('general-tab-copy-json');
    fireEvent.click(summaryBtn);
    expect(summaryBtn.textContent).toBe('已复制');
    fireEvent.click(jsonBtn);
    expect(jsonBtn.textContent).toBe('已复制');
  });
});
