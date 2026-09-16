// src/entities/permission/permissionState.ts
import { create } from 'zustand';

import type { PermissionRequest } from '../../shared/api';

/**
 * 工具审批状态 — M1 工具安全加固。
 *
 * 后端 agent 循环在分发敏感工具前发出 `state: 'permission_request'`
 * 流事件（携带 PermissionRequest 载荷），然后阻塞等待（最长 300s，
 * fail-closed）。本 store 持有「当前待审批请求」，驱动 ApprovalDialog
 * 模态框的显示/隐藏。
 *
 * 状态转移:
 *   null ──setFromEvent()──▶ PermissionRequest (对话框弹出)
 *     ▲                          │
 *     └──────── resolve() ───────┘ (批准/拒绝/流结束/流错误)
 *
 * 同一时刻至多一个待审批请求（后端单 agent 循环串行卡点）；
 * 重复 setFromEvent 直接替换（后到者覆盖，与后端 gate 行为一致）。
 *
 * S4 (2026-09-06) 多会话并行：请求记录归属会话（session_id），侧边栏
 * 据此按会话聚合"待审批"注意力点；resolve(sessionId) 定向清除 ——
 * 会话 A 的流结束不能误关会话 B 的审批对话框。无参 resolve() 保留
 * ApprovalDialog 等旧调用方的全清语义。
 */
export type PendingPermissionRequest = PermissionRequest & { /** 事件来源会话（S4） */ session_id?: string };

export interface PermissionState {
  /** 按会话归档的挂起请求 (2026-09 修复: 并行会话互不覆盖) */
  pendingBySession: Record<string, PendingPermissionRequest>;
  /** 当前待待审批请求；null 表示无挂起审批（对话框隐藏） */
  currentRequest: PendingPermissionRequest | null;
  /** 流事件到达 → 弹出对话框（不可变替换，不 mutate 旧对象）；sessionId 记录归属 */
  setFromEvent: (payload: PermissionRequest, sessionId?: string) => void;
  /** 审批完成 / 流结束 / 流错误 → 关闭对话框；传 sessionId 时仅清除该会话的请求 */
  resolve: (sessionId?: string) => void;
}

function pickDisplayedPermission(
  pending: Record<string, PendingPermissionRequest>,
): PendingPermissionRequest | null {
  const list = Object.values(pending);
  return list.length > 0 ? list[0] : null; // 插入序 = 到达序, 展示最老的
}

export const usePermissionState = create<PermissionState>((set) => ({
  currentRequest: null,
  pendingBySession: {},
  // 浅拷贝载荷：流事件对象来自 IPC 反序列化，复制一份避免调用方
  // 后续 mutate 同一引用造成 UI 与 store 不一致。
  setFromEvent: (payload, sessionId) =>
    set((prev) => {
      const request: PendingPermissionRequest = { ...payload, session_id: sessionId };
      // 2026-09 修复: 请求按会话归档而非单槽替换 —— 旧实现里并行会话 A
      // 卡在审批时 B 的请求会顶掉 A 且永不恢复(后端 gate 300s fail-closed,
      // 任务静默失败)。对话框仍展示一条; 已展示的不被后来者抢走。
      const key = sessionId ?? '__global__';
      const pending = { ...prev.pendingBySession, [key]: request };
      const displayed = prev.currentRequest;
      // 同会话的后续请求 = 替换已展示的(保留旧语义, 对话框随之重置);
      // 异会话请求不抢夺已展示的 —— 这是 2026-09 修复的核心:
      // A 卡审批时 B 的请求此前会把 A 顶掉且永不恢复。
      const currentRequest =
        displayed == null ||
        (displayed.session_id ?? null) === (sessionId ?? null)
          ? request
          : displayed;
      return { pendingBySession: pending, currentRequest };
    }),
  resolve: (sessionId) =>
    set((prev) => {
      // 未指定会话 = 全清（ApprovalDialog 批准/拒绝后调用）
      if (sessionId == null) return { currentRequest: null, pendingBySession: {} };
      const pending: Record<string, PendingPermissionRequest> = {};
      let removedDisplayed = false;
      for (const [k, req] of Object.entries(prev.pendingBySession)) {
        if (req.session_id === sessionId) {
          if (prev.currentRequest === req) removedDisplayed = true;
          continue;
        }
        pending[k] = req;
      }
      if (!removedDisplayed) return { pendingBySession: pending };
      return { pendingBySession: pending, currentRequest: pickDisplayedPermission(pending) };
    }),
}));
