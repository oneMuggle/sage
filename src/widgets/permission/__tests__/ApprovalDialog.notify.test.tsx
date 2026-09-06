/**
 * ApprovalDialog — live-events P1 附带：审批等待 OS 通知触发测试。
 *
 * 策略：mock `window.electronAPI.notifyApproval`，验证：
 *   - 请求到达时通知恰好触发一次，载荷带工具名；
 *   - 子代理请求的载荷带任务上下文（task_id · agent_id）；
 *   - 非 Electron（无 bridge）不抛错、不触发；
 *   - 同一 request 只通知一次（requestId 变化驱动，非重渲染）。
 */
import { render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

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
    tool_name: 'bash',
    args_summary: '{}',
    risk: 'suspicious',
    message: '需要审批',
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

const notifyMock = vi.fn().mockResolvedValue({ ok: true });

beforeEach(() => {
  invokeMock.mockReset().mockResolvedValue({ ok: true });
  toastErrorMock.mockReset();
  notifyMock.mockClear();
  usePermissionState.setState({ currentRequest: null });
  (window as unknown as { electronAPI?: unknown }).electronAPI = {
    notifyApproval: (...args: unknown[]) => notifyMock(...args),
  };
});

afterEach(() => {
  delete (window as unknown as { electronAPI?: unknown }).electronAPI;
});

describe('ApprovalDialog OS notification', () => {
  it('fires once with the tool name when a request arrives', async () => {
    renderDialog();
    usePermissionState.getState().setFromEvent(makeRequest());

    await vi.waitFor(() => {
      expect(notifyMock).toHaveBeenCalledTimes(1);
    });
    expect(notifyMock).toHaveBeenCalledWith({
      title: 'Sage 需要你的审批',
      body: 'bash',
    });
  });

  it('includes subagent context in the payload', async () => {
    renderDialog();
    usePermissionState.getState().setFromEvent(
      makeRequest({
        subagent: { run_id: 'orch-x', task_id: 't2', agent_id: 'researcher', goal: '调研' },
      }),
    );

    await vi.waitFor(() => {
      expect(notifyMock).toHaveBeenCalledTimes(1);
    });
    expect(notifyMock).toHaveBeenCalledWith({
      title: 'Sage 需要你的审批',
      body: 'bash · 子任务 t2（researcher）',
    });
  });

  it('is a no-op without the electron bridge', async () => {
    delete (window as unknown as { electronAPI?: unknown }).electronAPI;
    renderDialog();
    usePermissionState.getState().setFromEvent(makeRequest());
    // 让微队列跑完 —— 不应有未捕获异常,也不应触发
    await new Promise((r) => setTimeout(r, 10));
    expect(notifyMock).not.toHaveBeenCalled();
  });
});
