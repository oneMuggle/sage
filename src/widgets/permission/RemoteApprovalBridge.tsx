/**
 * RemoteApprovalBridge — Workspace MCP Server M5a.
 *
 * 远程工作区的写入 / 命令审批不来自聊天流事件，而是直接挂在后端全局
 * ApprovalGate 上（工具名 `remote_mcp.*`）。本组件每 3 秒拉一次
 * `permissions_pending`，把远程请求推进 usePermissionState（会话键
 * `__remote_mcp__`），由现有 ApprovalDialog 展示和应答；请求在别处
 * （Telegram / 超时）被处理后自动移除。
 *
 * 渲染 null；挂在 App 的 ApprovalDialog 旁。
 */
import { useEffect } from 'react';

import { usePermissionState } from '../../entities/permission/permissionState';
import type { PermissionRequest } from '../../shared/api';
import { isDemoMode } from '../../shared/api/demoFlag';
import { invoke } from '../../shared/api/desktopInvoke';

const REMOTE_APPROVAL_SESSION = '__remote_mcp__';
const REMOTE_PREFIX = 'remote_mcp.';
const POLL_MS = 3000;

function syncRemoteApprovals(pending: PermissionRequest[]): void {
  const remote = pending.filter((r) => typeof r.tool_name === 'string' && r.tool_name.startsWith(REMOTE_PREFIX));
  const state = usePermissionState.getState();
  const current = Object.values(state.pendingBySession).find((r) => r.session_id === REMOTE_APPROVAL_SESSION);
  if (current && !remote.some((r) => r.request_id === current.request_id)) {
    // 已在别处应答 / 超时
    state.resolve(REMOTE_APPROVAL_SESSION);
  }
  const next = remote[0];
  const latest = usePermissionState.getState();
  const stillShown = Object.values(latest.pendingBySession).some(
    (r) => r.session_id === REMOTE_APPROVAL_SESSION && r.request_id === next?.request_id,
  );
  if (next && !stillShown) latest.setFromEvent(next, REMOTE_APPROVAL_SESSION);
}

export function RemoteApprovalBridge(): null {
  useEffect(() => {
    if (isDemoMode()) return undefined;
    let cancelled = false;
    let inFlight = false;
    const tick = async () => {
      if (inFlight || cancelled) return;
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
      inFlight = true;
      try {
        const pending = await invoke<PermissionRequest[]>('permissions_pending');
        if (!cancelled && Array.isArray(pending)) syncRemoteApprovals(pending);
      } catch {
        /* 后端未就绪 / 断连：下一轮再试 */
      } finally {
        inFlight = false;
      }
    };
    void tick();
    const timer = setInterval(() => void tick(), POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);
  return null;
}
