/**
 * 对标 S3: 权限三档切换 + 自动放行计数徽记。
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { PermissionModeSwitch, formatPermissionModeJson, formatPermissionModeMarkdown } from '../PermissionModeSwitch';

const getPreset = vi.fn();
const setPreset = vi.fn();
const getSessionAutoApprovals = vi.fn();
const listSessionRememberedRules = vi.fn();
const deleteSessionRememberedRule = vi.fn();
const clearSessionRememberedRules = vi.fn();
const confirmDialogMock = vi.fn();
const toastSuccess = vi.fn();
const toastError = vi.fn();

vi.mock('../../../shared/api/permissionApi', async () => {
  const actual = await vi.importActual<typeof import('../../../shared/api/permissionApi')>(
    '../../../shared/api/permissionApi',
  );
  return {
    ...actual,
    permissionApi: {
      getPreset: (...a: unknown[]) => getPreset(...a),
      setPreset: (...a: unknown[]) => setPreset(...a),
      getSessionAutoApprovals: (...a: unknown[]) => getSessionAutoApprovals(...a),
      listSessionRememberedRules: (...a: unknown[]) => listSessionRememberedRules(...a),
      deleteSessionRememberedRule: (...a: unknown[]) => deleteSessionRememberedRule(...a),
      clearSessionRememberedRules: (...a: unknown[]) => clearSessionRememberedRules(...a),
    },
  };
});

vi.mock('../../../shared/ui/ConfirmDialog/confirmService', () => ({
  confirmDialog: (...a: unknown[]) => confirmDialogMock(...a),
}));

vi.mock('sonner', () => ({
  toast: {
    success: (...a: unknown[]) => toastSuccess(...a),
    error: (...a: unknown[]) => toastError(...a),
  },
}));

const renderSwitch = (sessionId: string | null) =>
  render(
    <I18nProvider defaultLocale="zh">
      <PermissionModeSwitch sessionId={sessionId} />
    </I18nProvider>,
  );

beforeEach(() => {
  getPreset
    .mockReset()
    .mockResolvedValue({ preset: 'standard', mode: 'workspace_write', custom: false });
  setPreset.mockReset().mockResolvedValue(undefined);
  listSessionRememberedRules.mockReset().mockResolvedValue([]);
  deleteSessionRememberedRule.mockReset().mockResolvedValue([]);
  clearSessionRememberedRules.mockReset().mockResolvedValue([]);
  confirmDialogMock.mockReset().mockResolvedValue(true);
  toastSuccess.mockReset();
  toastError.mockReset();
  getSessionAutoApprovals.mockReset().mockResolvedValue({
    session_id: 's1',
    count: 3,
    total: 5,
    items: [
      {
        seq: 1,
        session_id: 's1',
        tool_name: 'write_file',
        capability: 'write',
        mode: 'workspace_write',
        reason: 'inside_workspace',
        summary: 'path=a.txt',
        created_at: 1_700_000_000,
      },
    ],
  });
});

describe('PermissionModeSwitch', () => {
  it('loads the current preset and switches via the menu', async () => {
    renderSwitch(null);
    await waitFor(() => expect(getPreset).toHaveBeenCalled());
    const button = screen.getByTestId('permission-mode-button');
    await waitFor(() => expect(button.textContent).toContain('标准'));

    fireEvent.click(button);
    fireEvent.click(screen.getByTestId('permission-preset-auto'));
    await waitFor(() => expect(setPreset).toHaveBeenCalledWith('auto'));
    expect(button.textContent).toContain('自动');
  });

  it('shows the auto-approval badge and the audit list for a session', async () => {
    renderSwitch('s1');
    const badge = await screen.findByTestId('auto-approval-badge');
    expect(badge.textContent).toContain('3');
    await act(async () => {
      fireEvent.click(badge);
    });
    expect(screen.getByTestId('auto-approval-audit')).toBeInTheDocument();
    expect(screen.getAllByTestId('auto-approval-item')).toHaveLength(1);
    expect(screen.getByText('write_file')).toBeInTheDocument();
  });

  it('hides the badge when there is no session', async () => {
    renderSwitch(null);
    await waitFor(() => expect(getPreset).toHaveBeenCalled());
    expect(screen.queryByTestId('auto-approval-badge')).not.toBeInTheDocument();
    expect(getSessionAutoApprovals).not.toHaveBeenCalled();
    expect(listSessionRememberedRules).not.toHaveBeenCalled();
  });

  const SESSION_RULES = [
    { tool_pattern: 'bash', decision: 'allow', plugin_name: null, plugin_status: null },
    {
      tool_pattern: 'plugin__ghost__*',
      decision: 'deny',
      plugin_name: null,
      plugin_status: 'missing',
    },
  ];

  const openAuditWithSessionRules = async () => {
    getSessionAutoApprovals.mockResolvedValue({
      session_id: 's1',
      count: 0,
      total: 0,
      items: [],
    });
    listSessionRememberedRules.mockResolvedValue(SESSION_RULES);
    renderSwitch('s1');
    const badge = await screen.findByTestId('auto-approval-badge');
    await act(async () => {
      fireEvent.click(badge);
    });
    return badge;
  };

  it('shows the badge for session rules at zero auto-approvals and lists them', async () => {
    const badge = await openAuditWithSessionRules();
    expect(badge.textContent).toContain('本会话已记住 2');
    expect(screen.getByTestId('session-rules-section')).toBeInTheDocument();
    expect(screen.getAllByTestId('session-rule-item')).toHaveLength(2);
    expect(screen.getByText('bash')).toBeInTheDocument();
    expect(screen.getByText('plugin__ghost__*')).toBeInTheDocument();
    expect(screen.getByText('允许')).toBeInTheDocument();
    expect(screen.getByText('拒绝')).toBeInTheDocument();
    expect(screen.getByText('插件无记录')).toBeInTheDocument();
  });

  it('revokes a session rule and adopts the returned list', async () => {
    await openAuditWithSessionRules();
    deleteSessionRememberedRule.mockResolvedValue([SESSION_RULES[1]]);

    fireEvent.click(screen.getByTestId('session-rule-revoke-0'));

    await waitFor(() =>
      expect(deleteSessionRememberedRule).toHaveBeenCalledWith('s1', SESSION_RULES[0]),
    );
    await waitFor(() => expect(screen.getAllByTestId('session-rule-item')).toHaveLength(1));
    expect(screen.queryByText('bash')).not.toBeInTheDocument();
  });

  it('keeps session rules and toasts when revoke fails', async () => {
    await openAuditWithSessionRules();
    deleteSessionRememberedRule.mockRejectedValue(new Error('backend down'));

    fireEvent.click(screen.getByTestId('session-rule-revoke-0'));

    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(screen.getAllByTestId('session-rule-item')).toHaveLength(2);
  });

  it('clears session rules only after confirm', async () => {
    await openAuditWithSessionRules();
    confirmDialogMock.mockResolvedValue(false);
    fireEvent.click(screen.getByTestId('session-rules-clear'));
    await waitFor(() => expect(confirmDialogMock).toHaveBeenCalled());
    expect(clearSessionRememberedRules).not.toHaveBeenCalled();
    expect(screen.getAllByTestId('session-rule-item')).toHaveLength(2);

    confirmDialogMock.mockResolvedValue(true);
    fireEvent.click(screen.getByTestId('session-rules-clear'));
    await waitFor(() => expect(clearSessionRememberedRules).toHaveBeenCalledWith('s1'));
    await waitFor(() =>
      expect(screen.queryByTestId('session-rules-section')).not.toBeInTheDocument(),
    );
  });

  it('formats and copies permission mode summary as Markdown and JSON', async () => {
    const md = formatPermissionModeMarkdown({
      sessionId: 's1',
      preset: 'standard',
      custom: false,
      count: 1,
      items: [
        {
          seq: 1,
          session_id: 's1',
          tool_name: 'write_file',
          capability: 'write',
          mode: 'workspace_write',
          reason: 'inside_workspace',
          summary: 'path=a.txt',
          created_at: 1_700_000_000,
        },
      ],
    });
    expect(md).toContain('# 会话权限模式与自动放行审计 (Permission Mode Summary)');
    expect(md).toContain('write_file');
    expect(
      formatPermissionModeMarkdown({
        sessionId: null,
        preset: 'careful',
        custom: true,
        count: 0,
        items: [],
      }),
    ).toContain('_暂无自动放行审计记录_');

    const parsed = JSON.parse(
      formatPermissionModeJson({
        sessionId: 's1',
        preset: 'auto',
        custom: false,
        count: 0,
        items: [],
      }),
    );
    expect(parsed.preset).toBe('auto');
  });
});
