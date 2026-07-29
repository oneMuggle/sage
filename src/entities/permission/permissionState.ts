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
 */
export interface PermissionState {
  /** 当前待审批请求；null 表示无挂起审批（对话框隐藏） */
  currentRequest: PermissionRequest | null;
  /** 流事件到达 → 弹出对话框（不可变替换，不 mutate 旧对象） */
  setFromEvent: (payload: PermissionRequest) => void;
  /** 审批完成 / 流结束 / 流错误 → 关闭对话框 */
  resolve: () => void;
}

export const usePermissionState = create<PermissionState>((set) => ({
  currentRequest: null,
  // 浅拷贝载荷：流事件对象来自 IPC 反序列化，复制一份避免调用方
  // 后续 mutate 同一引用造成 UI 与 store 不一致。
  setFromEvent: (payload) => set({ currentRequest: { ...payload } }),
  resolve: () => set({ currentRequest: null }),
}));
