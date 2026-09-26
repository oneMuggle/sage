// @vitest-environment jsdom
import { act, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { usePermissionState } from '../../../entities/permission/permissionState';
import { RemoteApprovalBridge } from '../RemoteApprovalBridge';

const mocks = vi.hoisted(() => ({ invoke: vi.fn(), demo: false }));

vi.mock('../../../shared/api/desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mocks.invoke(...args),
}));
vi.mock('../../../shared/api/demoFlag', () => ({ isDemoMode: () => mocks.demo }));

function req(id: string, tool = 'remote_mcp.write_file') {
  return { request_id: id, tool_name: tool, args_summary: '{}', risk: 'suspicious', message: 'm', created_at: 1 };
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
  usePermissionState.setState({ currentRequest: null, pendingBySession: {} });
});

afterEach(() => {
  vi.useRealTimers();
});

describe('RemoteApprovalBridge', () => {
  it('pushes remote_mcp.* requests into the approval store, ignoring others', async () => {
    mocks.invoke.mockResolvedValue([req('local', 'write_file'), req('r1')]);
    render(<RemoteApprovalBridge />);
    await flush();
    expect(mocks.invoke).toHaveBeenCalledWith('permissions_pending');
    const current = usePermissionState.getState().currentRequest;
    expect(current?.request_id).toBe('r1');
    expect(current?.session_id).toBe('__remote_mcp__');
  });

  it('removes a request answered elsewhere and shows the next one', async () => {
    mocks.invoke.mockResolvedValueOnce([req('r1')]).mockResolvedValueOnce([req('r2')]).mockResolvedValue([]);
    render(<RemoteApprovalBridge />);
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
    render(<RemoteApprovalBridge />);
    await flush();
    const state = usePermissionState.getState();
    expect(state.currentRequest?.request_id).toBe('chat');
    expect(Object.values(state.pendingBySession).map((r) => r.request_id)).toContain('r1');
  });

  it('does nothing in demo mode and survives backend errors', async () => {
    mocks.demo = true;
    render(<RemoteApprovalBridge />);
    await flush(3000);
    expect(mocks.invoke).not.toHaveBeenCalled();
  });

  it('swallows backend errors', async () => {
    mocks.invoke.mockRejectedValue(new Error('down'));
    render(<RemoteApprovalBridge />);
    await flush();
    expect(usePermissionState.getState().currentRequest).toBeNull();
  });
});
