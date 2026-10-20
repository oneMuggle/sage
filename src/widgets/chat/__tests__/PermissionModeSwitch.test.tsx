/**
 * 对标 S3: 权限三档切换 + 自动放行计数徽记。
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import {
  PermissionModeSwitch,
  formatPermissionModeJson,
  formatPermissionModeMarkdown,
} from '../PermissionModeSwitch';

const getPreset = vi.fn();
const setPreset = vi.fn();
const getSessionAutoApprovals = vi.fn();

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
    },
  };
});

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const renderSwitch = (sessionId: string | null) =>
  render(
    <I18nProvider defaultLocale="zh">
      <PermissionModeSwitch sessionId={sessionId} />
    </I18nProvider>,
  );

beforeEach(() => {
  getPreset.mockReset().mockResolvedValue({ preset: 'standard', mode: 'workspace_write', custom: false });
  setPreset.mockReset().mockResolvedValue(undefined);
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

    renderSwitch('s1');
    await waitFor(() => expect(getPreset).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId('permission-mode-copy-md'));
    expect(screen.getByTestId('permission-mode-copy-md').textContent).toContain('已复制 MD');
    fireEvent.click(screen.getByTestId('permission-mode-copy-json'));
    expect(screen.getByTestId('permission-mode-copy-json').textContent).toContain('已复制 JSON');
  });
});
