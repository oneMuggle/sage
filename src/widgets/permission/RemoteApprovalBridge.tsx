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
import { useEffect, useRef } from 'react';
import { toast } from 'sonner';

import { usePermissionState } from '../../entities/permission/permissionState';
import type { PermissionRequest } from '../../shared/api';
import { isDemoMode } from '../../shared/api/demoFlag';
import { invoke } from '../../shared/api/desktopInvoke';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';

const REMOTE_APPROVAL_SESSION = '__remote_mcp__';
const REMOTE_PREFIX = 'remote_mcp.';
const POLL_MS = 3000;

const RISK_LABEL_KEYS: Readonly<Record<PermissionRequest['risk'], TranslationKey>> = {
  safe: 'permission.risk.safe',
  suspicious: 'permission.risk.suspicious',
  destructive: 'permission.risk.destructive',
};

/** created_at 是 epoch 秒（浮点）；异常值回退为 0，避免显示「等待 负数」。 */
function formatWaited(createdAt: number): string {
  const elapsedSec = createdAt > 0 ? Math.max(0, Math.round(Date.now() / 1000 - createdAt)) : 0;
  if (elapsedSec >= 60) return `${Math.round(elapsedSec / 60)}min`;
  return `${elapsedSec}s`;
}

/**
 * P0-4: 请求在别处被处理后此前只是静默关窗。这里补一条回执 —
 * 高危操作在桌面端曾完全失去本地审计锚点（记忆写入有提示、危险操作
 * 审批却没有，可撤销性倒挂）。
 *
 * 只陈述「已离开待批队列」这一可观测事实：pending 列表不含历史，前端
 * 无法区分是远程批准、远程拒绝还是后端超时，故不猜测结果。
 */
function notifyResolvedRemotely(
  request: PermissionRequest,
  t: (key: TranslationKey) => string,
): void {
  const risk = RISK_LABEL_KEYS[request.risk] ? request.risk : ('safe' as const);
  const desc = t('permission.remote_resolved.desc')
    .replace('{tool}', request.tool_name)
    .replace('{risk}', t(RISK_LABEL_KEYS[risk]))
    .replace('{wait}', formatWaited(request.created_at));
  toast.info(t('permission.remote_resolved'), { description: desc });
}

function syncRemoteApprovals(
  pending: PermissionRequest[],
  t: (key: TranslationKey) => string,
  notified: Set<string>,
): void {
  const remote = pending.filter((r) => typeof r.tool_name === 'string' && r.tool_name.startsWith(REMOTE_PREFIX));
  const state = usePermissionState.getState();
  const current = Object.values(state.pendingBySession).find((r) => r.session_id === REMOTE_APPROVAL_SESSION);
  if (
    current &&
    !notified.has(current.request_id) &&
    !remote.some((r) => r.request_id === current.request_id)
  ) {
    // 已在别处应答 / 超时
    state.resolve(REMOTE_APPROVAL_SESSION);
    // 轮询每 3s 一次，而 resolve 与 store 更新之间可能跨过一个 tick；
    // 不做幂等就会对同一条请求反复弹回执。按 request_id 去重。
    notified.add(current.request_id);
    notifyResolvedRemotely(current, t);
  }
  const next = remote[0];
  const latest = usePermissionState.getState();
  const stillShown = Object.values(latest.pendingBySession).some(
    (r) => r.session_id === REMOTE_APPROVAL_SESSION && r.request_id === next?.request_id,
  );
  if (next && !stillShown) latest.setFromEvent(next, REMOTE_APPROVAL_SESSION);
}

export function RemoteApprovalBridge(): null {
  const { t } = useI18n();
  // 回执去重集合随实例存活：重挂载即视为新会话，允许再次告知。
  const notifiedRef = useRef<Set<string>>(new Set());
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
        if (!cancelled && Array.isArray(pending)) syncRemoteApprovals(pending, t, notifiedRef.current);
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
  }, [t]);
  return null;
}
