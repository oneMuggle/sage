// src/widgets/chat/SubagentLivePanel.tsx
//
// live-events P0 (2026-09-06) —— 聊天流内联的子代理实时执行面板。
//
// 背景：编排派发后 conductor 阻塞在 dispatch_subagents 工具调用里，
// 消息气泡只有"Delegate <goal>"静态卡片，用户只能被动等待。本组件
// 从 chatStreamStore.taskBoard.live（由 subagent_event 镜像事件喂）
// 读取每个子任务的实时步骤，在流式指示器下方逐行展示 —— ZCode Task
// 工具"实时子代理进度"的轻量对等物（完整时间线在右侧 Drawer）。
//
// 渲染约定：仅 isLoading 且有 running 子任务时渲染；每行 =
// 状态符 + [task · agent] + live_step（后端预拼装,截断防刷屏）。

import { selectSessionSlots, useChatStreamStore } from '../../features/send-message/chatStreamStore';
import { useStore } from '../../shared/lib/store';

export function SubagentLivePanel() {
  // S2: 读当前会话的键控槽位 —— 并行会话各自的面板互不串扰
  const currentSessionId = useStore((s) => s.currentSessionId);
  const taskBoard = useChatStreamStore((s) => selectSessionSlots(s, currentSessionId).taskBoard);
  const isLoading = useChatStreamStore((s) => {
    const streaming = selectSessionSlots(s, currentSessionId).streaming;
    return streaming !== null && streaming.state !== 'done';
  });

  if (!isLoading || !taskBoard) return null;

  const rows = taskBoard.plan
    .map((item) => ({ item, live: taskBoard.live?.[item.task_id] }))
    .filter(
      ({ item, live }) =>
        taskBoard.statuses[item.task_id]?.status === 'running' &&
        Boolean(live?.liveStep),
    );

  if (rows.length === 0) return null;

  return (
    <div
      data-testid="subagent-live-panel"
      className="mx-auto max-w-3xl mb-2 px-3 py-2 rounded-radius-sm border border-border bg-bg-subtle text-[11px] leading-relaxed"
    >
      <div className="text-muted mb-1">子代理实时执行（详情点右侧任务树展开）</div>
      <ul className="space-y-0.5">
        {rows.map(({ item, live }) => (
          <li key={item.task_id} className="flex items-center gap-2 min-w-0">
            <span className="text-primary animate-pulse shrink-0">◐</span>
            <span className="text-text-tertiary shrink-0">
              [{item.task_id} · {item.agent_id}]
            </span>
            <span className="text-text-secondary truncate">{live!.liveStep}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
