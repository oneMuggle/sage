// src/entities/permission/__tests__/permissionState.test.ts
import { beforeEach, describe, expect, it } from 'vitest';

import type { PermissionRequest } from '../../../shared/api';
import { usePermissionState } from '../permissionState';

function makeRequest(overrides: Partial<PermissionRequest> = {}): PermissionRequest {
  return {
    request_id: 'req-1',
    tool_name: 'terminal',
    args_summary: '{"command": "ls"}',
    risk: 'safe',
    message: 'execute 能力工具 terminal 需要用户逐次确认',
    created_at: 1753718400.123,
    ...overrides,
  };
}

describe('usePermissionState', () => {
  beforeEach(() => {
    usePermissionState.setState({ currentRequest: null });
  });

  it('initial state: no pending request', () => {
    expect(usePermissionState.getState().currentRequest).toBeNull();
  });

  it('setFromEvent() stores the request (dialog trigger)', () => {
    const req = makeRequest();
    usePermissionState.getState().setFromEvent(req);
    expect(usePermissionState.getState().currentRequest).toEqual(req);
  });

  it('setFromEvent() copies the payload (caller mutation must not leak)', () => {
    const req = makeRequest();
    usePermissionState.getState().setFromEvent(req);
    // 模拟 IPC 层复用/篡改载荷对象
    req.tool_name = 'mutated';
    expect(usePermissionState.getState().currentRequest?.tool_name).toBe('terminal');
  });

  it('setFromEvent() replaces an in-flight request (后到者覆盖)', () => {
    usePermissionState.getState().setFromEvent(makeRequest({ request_id: 'req-1' }));
    usePermissionState.getState().setFromEvent(makeRequest({ request_id: 'req-2' }));
    expect(usePermissionState.getState().currentRequest?.request_id).toBe('req-2');
  });

  it('resolve() clears the request (dialog close)', () => {
    usePermissionState.getState().setFromEvent(makeRequest());
    usePermissionState.getState().resolve();
    expect(usePermissionState.getState().currentRequest).toBeNull();
  });

  it('resolve() is idempotent on empty state', () => {
    usePermissionState.getState().resolve();
    expect(usePermissionState.getState().currentRequest).toBeNull();
  });

  it('updates immutably: setState produces a new request object reference', () => {
    usePermissionState.getState().setFromEvent(makeRequest({ request_id: 'a' }));
    const first = usePermissionState.getState().currentRequest;
    usePermissionState.getState().setFromEvent(makeRequest({ request_id: 'b' }));
    const second = usePermissionState.getState().currentRequest;
    expect(second).not.toBe(first);
  });
});
