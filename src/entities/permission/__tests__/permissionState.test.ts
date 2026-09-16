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
    usePermissionState.setState({ currentRequest: null, pendingBySession: {} });
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

  it('setFromEvent() keeps displayed request; later requests queue per session (2026-09 修复)', () => {
    // 后到者不再覆盖已展示的请求 —— 并行会话 A 卡审批时 B 的请求此前会把
    // A 顶掉且永不恢复(后端 gate 300s fail-closed, 任务静默失败)。
    // 现按会话归档: 已展示的保持; 全清后展示最老的剩余请求。
    usePermissionState.getState().setFromEvent(makeRequest({ request_id: 'req-1' }), 'sess-A');
    usePermissionState.getState().setFromEvent(makeRequest({ request_id: 'req-2' }), 'sess-B');
    expect(usePermissionState.getState().currentRequest?.request_id).toBe('req-1');
    expect(Object.keys(usePermissionState.getState().pendingBySession)).toHaveLength(2);
    usePermissionState.getState().resolve('sess-A');
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

  it('updates immutably: setFromEvent produces a new object per session slot', () => {
    usePermissionState.getState().setFromEvent(makeRequest({ request_id: 'a' }));
    const first = usePermissionState.getState().currentRequest;
    usePermissionState.getState().setFromEvent(makeRequest({ request_id: 'b' }));
    // 已展示的请求保持原引用; 新请求进入 pendingBySession 新槽位
    expect(usePermissionState.getState().currentRequest).toBe(first);
    const second = usePermissionState.getState().pendingBySession['__global__'];
    expect(second.request_id).toBe('b');
    expect(second).not.toBe(first);
  });
});
