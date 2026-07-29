/**
 * ApprovalDialog — M1 工具审批模态框渲染 + 应答行为测试。
 *
 * 策略:
 *   - mock desktopInvoke.invoke（与 useChat.test.ts 同约定）,验证
 *     permissions_answer 的调用参数与 store 清理。
 *   - mock sonner.toast,验证 ok=false / 抛错时的错误暴露。
 *   - 用 usePermissionState.setState 直接灌入请求（store 单元测试已覆盖
 *     setFromEvent,这里只关心「store 有请求 → 对话框行为」）。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { usePermissionState } from '../../../entities/permission/permissionState';
import type { PermissionRequest } from '../../../shared/api';
import { I18nProvider } from '../../../shared/lib/i18n';
import { ApprovalDialog } from '../ApprovalDialog';

const invokeMock = vi.fn();
vi.mock('../../../shared/api/desktopInvoke', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
}));

const toastErrorMock = vi.fn();
vi.mock('sonner', () => ({
  toast: { error: (...args: unknown[]) => toastErrorMock(...args) },
}));

function makeRequest(overrides: Partial<PermissionRequest> = {}): PermissionRequest {
  return {
    request_id: 'req-42',
    tool_name: 'terminal',
    args_summary: '{"command": "rm -rf /tmp/x"}',
    risk: 'destructive',
    message: 'execute 能力工具 terminal 需要用户逐次确认',
    created_at: 1753718400.123,
    ...overrides,
  };
}

function renderDialog(): void {
  render(
    <I18nProvider>
      <ApprovalDialog />
    </I18nProvider>,
  );
}

function seedRequest(overrides: Partial<PermissionRequest> = {}): PermissionRequest {
  const req = makeRequest(overrides);
  usePermissionState.getState().setFromEvent(req);
  return req;
}

beforeEach(() => {
  invokeMock.mockReset();
  toastErrorMock.mockReset();
  invokeMock.mockResolvedValue({ ok: true });
  usePermissionState.setState({ currentRequest: null });
});

describe('ApprovalDialog', () => {
  it('renders nothing when no request is pending', () => {
    renderDialog();
    expect(screen.queryByTestId('permission-approval-dialog')).toBeNull();
  });

  it('renders tool name, risk badge, message and args when store has a request', () => {
    seedRequest();
    renderDialog();

    expect(screen.getByTestId('permission-approval-dialog')).toBeInTheDocument();
    expect(screen.getByTestId('permission-tool-name')).toHaveTextContent('terminal');
    expect(screen.getByTestId('permission-risk-badge')).toHaveTextContent('危险');
    expect(screen.getByTestId('permission-message')).toHaveTextContent(
      'execute 能力工具 terminal 需要用户逐次确认',
    );
    expect(screen.getByTestId('permission-args')).toHaveTextContent('rm -rf /tmp/x');
  });

  it('renders neutral/amber badges for safe/suspicious risk levels', () => {
    seedRequest({ risk: 'suspicious' });
    const { unmount } = render(
      <I18nProvider>
        <ApprovalDialog />
      </I18nProvider>,
    );
    expect(screen.getByTestId('permission-risk-badge')).toHaveTextContent('可疑');
    unmount();

    usePermissionState.getState().setFromEvent(makeRequest({ risk: 'safe' }));
    render(
      <I18nProvider>
        <ApprovalDialog />
      </I18nProvider>,
    );
    const badges = screen.getAllByTestId('permission-risk-badge');
    expect(badges[badges.length - 1]).toHaveTextContent('安全');
  });

  it('approve click invokes permissions_answer with approved=true and clears the store', async () => {
    seedRequest({ request_id: 'req-approve' });
    renderDialog();

    fireEvent.click(screen.getByTestId('permission-approve'));

    await waitFor(() => {
      expect(invokeMock).toHaveBeenCalledWith('permissions_answer', {
        requestId: 'req-approve',
        approved: true,
        remember: false,
      });
    });
    await waitFor(() => {
      expect(usePermissionState.getState().currentRequest).toBeNull();
    });
    expect(screen.queryByTestId('permission-approval-dialog')).toBeNull();
    expect(toastErrorMock).not.toHaveBeenCalled();
  });

  it('remember checkbox is forwarded as remember=true', async () => {
    seedRequest({ request_id: 'req-remember' });
    renderDialog();

    fireEvent.click(screen.getByTestId('permission-remember'));
    fireEvent.click(screen.getByTestId('permission-approve'));

    await waitFor(() => {
      expect(invokeMock).toHaveBeenCalledWith('permissions_answer', {
        requestId: 'req-remember',
        approved: true,
        remember: true,
      });
    });
  });

  it('deny click invokes with approved=false and clears the store', async () => {
    seedRequest({ request_id: 'req-deny' });
    renderDialog();

    fireEvent.click(screen.getByTestId('permission-deny'));

    await waitFor(() => {
      expect(invokeMock).toHaveBeenCalledWith('permissions_answer', {
        requestId: 'req-deny',
        approved: false,
        remember: false,
      });
    });
    await waitFor(() => {
      expect(usePermissionState.getState().currentRequest).toBeNull();
    });
  });

  it('surfaces toast but still clears the store when backend answers ok=false', async () => {
    invokeMock.mockResolvedValueOnce({ ok: false, error: 'unknown_or_expired' });
    seedRequest({ request_id: 'req-expired' });
    renderDialog();

    fireEvent.click(screen.getByTestId('permission-approve'));

    await waitFor(() => {
      expect(toastErrorMock).toHaveBeenCalled();
    });
    expect(String(toastErrorMock.mock.calls[0][0])).toContain('unknown_or_expired');
    await waitFor(() => {
      expect(usePermissionState.getState().currentRequest).toBeNull();
    });
  });

  it('surfaces toast but still clears the store when invoke throws (IPC failure)', async () => {
    invokeMock.mockRejectedValueOnce(new Error('bridge down'));
    seedRequest({ request_id: 'req-ipc-fail' });
    renderDialog();

    fireEvent.click(screen.getByTestId('permission-deny'));

    await waitFor(() => {
      expect(toastErrorMock).toHaveBeenCalled();
    });
    expect(String(toastErrorMock.mock.calls[0][0])).toContain('bridge down');
    await waitFor(() => {
      expect(usePermissionState.getState().currentRequest).toBeNull();
    });
  });

  it('resets remember checkbox when a new request arrives', async () => {
    seedRequest({ request_id: 'req-a' });
    const { rerender } = render(
      <I18nProvider>
        <ApprovalDialog />
      </I18nProvider>,
    );

    fireEvent.click(screen.getByTestId('permission-remember'));
    expect((screen.getByTestId('permission-remember') as HTMLInputElement).checked).toBe(true);

    // 新请求替换 — 组件不卸载,局部 state 必须重置
    usePermissionState.getState().setFromEvent(makeRequest({ request_id: 'req-b' }));
    rerender(
      <I18nProvider>
        <ApprovalDialog />
      </I18nProvider>,
    );

    await waitFor(() => {
      expect((screen.getByTestId('permission-remember') as HTMLInputElement).checked).toBe(false);
    });
  });
});
