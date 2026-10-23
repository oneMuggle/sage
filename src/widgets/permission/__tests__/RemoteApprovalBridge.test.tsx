// @vitest-environment jsdom
import { act, render } from '@testing-library/react';
import { toast } from 'sonner';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { usePermissionState } from '../../../entities/permission/permissionState';
import { I18nProvider } from '../../../shared/lib/i18n';
import { RemoteApprovalBridge } from '../RemoteApprovalBridge';

const mocks = vi.hoisted(() => ({ invoke: vi.fn(), demo: false }));

vi.mock('../../../shared/api/desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mocks.invoke(...args),
}));
vi.mock('../../../shared/api/demoFlag', () => ({ isDemoMode: () => mocks.demo }));
vi.mock('sonner', () => ({
  toast: { info: vi.fn(), success: vi.fn(), error: vi.fn() },
}));

function req(id: string, tool = 'remote_mcp.write_file', createdAt = 1) {
  return {
    request_id: id,
    tool_name: tool,
    args_summary: '{}',
    risk: 'suspicious',
    message: 'm',
    created_at: createdAt,
  };
}

/** P0-4 起组件读取 i18n（回执文案），需在 I18nProvider 内渲染。 */
function renderBridge() {
  return render(
    <I18nProvider>
      <RemoteApprovalBridge />
    </I18nProvider>,
  );
}

async function flush(ms = 0) {
  await act(async () => {
    vi.advanceTimersByTime(ms);
    await Promise.resolve();
    await Promise.resolve();
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  mocks.demo = false;
  mocks.invoke.mockReset();
  // sonner 的 spy 由 vi.mock 工厂创建，跨用例累积，必须显式清零，
  // 否则前一个用例的回执会被计入下一个用例的断言。
  (toast.info as ReturnType<typeof vi.fn>).mockClear();
  (toast.success as ReturnType<typeof vi.fn>).mockClear();
  (toast.error as ReturnType<typeof vi.fn>).mockClear();
  usePermissionState.setState({ currentRequest: null, pendingBySession: {} });
});

afterEach(() => {
  vi.useRealTimers();
});

describe('RemoteApprovalBridge', () => {
  it('pushes remote_mcp.* requests into the approval store, ignoring others', async () => {
    mocks.invoke.mockResolvedValue([req('local', 'write_file'), req('r1')]);
    renderBridge();
    await flush();
    expect(mocks.invoke).toHaveBeenCalledWith('permissions_pending');
    const current = usePermissionState.getState().currentRequest;
    expect(current?.request_id).toBe('r1');
    expect(current?.session_id).toBe('__remote_mcp__');
  });

  it('removes a request answered elsewhere and shows the next one', async () => {
    mocks.invoke.mockResolvedValueOnce([req('r1')]).mockResolvedValueOnce([req('r2')]).mockResolvedValue([]);
    renderBridge();
    await flush();
    expect(usePermissionState.getState().currentRequest?.request_id).toBe('r1');
    await flush(3000);
    expect(usePermissionState.getState().currentRequest?.request_id).toBe('r2');
    await flush(3000);
    expect(usePermissionState.getState().currentRequest).toBeNull();
  });

  it('does not steal the dialog from a chat-session request', async () => {
    usePermissionState.getState().setFromEvent(req('chat', 'bash') as never, 'session-a');
    mocks.invoke.mockResolvedValue([req('r1')]);
    renderBridge();
    await flush();
    const state = usePermissionState.getState();
    expect(state.currentRequest?.request_id).toBe('chat');
    expect(Object.values(state.pendingBySession).map((r) => r.request_id)).toContain('r1');
  });

  it('does nothing in demo mode and survives backend errors', async () => {
    mocks.demo = true;
    renderBridge();
    await flush(3000);
    expect(mocks.invoke).not.toHaveBeenCalled();
  });

  it('swallows backend errors', async () => {
    mocks.invoke.mockRejectedValue(new Error('down'));
    renderBridge();
    await flush();
    expect(usePermissionState.getState().currentRequest).toBeNull();
  });

  // P0-4: 请求在别处（远程渠道/超时）被处理后，此前桌面端静默关窗，
  // 高危操作失去唯一的本地审计锚点。必须回执，且不猜测处理结果。
  it('P0-4 reports a receipt when a pending request disappears', async () => {
    const nowSec = Math.round(Date.now() / 1000);
    mocks.invoke.mockResolvedValueOnce([req('r1', 'remote_mcp.write_file', nowSec)]).mockResolvedValue([]);
    renderBridge();
    await flush();
    expect(toast.info).not.toHaveBeenCalled();

    await flush(3000);
    expect(toast.info).toHaveBeenCalledTimes(1);
    const [title, opts] = (toast.info as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      { description?: string },
    ];
    expect(title).toBeTruthy();
    expect(opts?.description).toContain('remote_mcp.write_file');
    // 等待时长取自 created_at（而非 1970 兜底值 0）
    expect(opts?.description).not.toMatch(/已等待 0s/);

    // 后续轮询不得对同一条请求重复回执
    await flush(3000);
    expect(toast.info).toHaveBeenCalledTimes(1);
  });
});
