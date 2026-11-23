// src/features/orch-notify/orchNotify.ts
//
// 编排通知点击 → 任务中心深链（M4.3a, 2026-11-23）。
//
// 主进程展示编排 run 终态 / 等待审批的 OS 通知；用户点击后回发
// 'sage:event:orch-notify-click'（preload 走通用 sage:event:* 通道）。
// 本模块负责把这次点击翻译成"打开对应会话 + 定位到那个子代理任务"。
//
// 深链三步与 TaskCenter 的子代理条目打开路径一致
// （src/features/task-center/useTaskCenterActions.ts）：
//   1. focusThread({sessionId, runId, taskId}) —— 聊天页 ProgressSection 消费
//   2. 右侧面板切到 progress 标签并展开
//   3. 路由跳到 /chat?session=<sessionId>（由调用方做，路由不在本模块）
//
// 浏览器 / dev 环境无 electron 桥时全部 no-op，不抛错（与 sessionNotify 同风格）。

import { useOrchestrationFocusStore } from '../../entities/orchestration/orchestrationFocusStore';
import { listen, type UnlistenFn } from '../../shared/api/desktopEvent';
import { useRightPanelStore } from '../right-panel/rightPanelStore';

/** 主进程回发的点击载荷。 */
export interface OrchNotifyClickPayload {
  sessionId: string;
  runId: string;
  taskId: string;
}

/** OS 通知点击 → 回调（主进程经 'sage:event:orch-notify-click' 回发）。 */
export function onOrchNotifyClick(
  handler: (payload: OrchNotifyClickPayload) => void,
): Promise<UnlistenFn | undefined> | undefined {
  const api = typeof window !== 'undefined' ? window.electronAPI : undefined;
  if (!api?.listen) return undefined;
  return listen<OrchNotifyClickPayload>('orch-notify-click', ({ payload }) =>
    handler(payload),
  ).catch(() => undefined);
}

/**
 * 把点击载荷写进编排定位 store + 右侧面板状态。
 *
 * 返回是否产生了有效定位（缺 runId 时为 false —— 没有 run 就无从定位）。
 * 路由跳转由调用方负责。
 */
export function focusOrchThread(payload: OrchNotifyClickPayload): boolean {
  if (!payload.runId) return false;
  useOrchestrationFocusStore.getState().focusThread({
    sessionId: payload.sessionId ?? '',
    runId: payload.runId,
    taskId: payload.taskId ?? '',
  });
  const panel = useRightPanelStore.getState();
  panel.setTab('progress');
  panel.setOpen(true);
  return true;
}
