// src/features/send-message/chatStreamStore.ts
//
// 流式 chat 进度状态机 — 2026-08-19 跨页面持久化改造
//
// 历史背景：原本 `streaming` / `streamingToolCalls` / `taskBoard` 都放在
// useChat 的 component-local useState 里。路由切换（chat → settings）会
// 卸载 Chat 页，这些 state 全部清空，导致用户切回时只看到 store 里的
// '🤔 思考中…' 占位符，看不到 LLM 真实进度（虽然后端 stream 还在跑，
//  权限确认 IPC 还能弹 — 与用户报告的现象完全一致）。
//
// 设计：
// - 独立 zustand store，module-singleton，跨组件实例 / 跨路由保留
// - 每个 action 校验 messageId，避免上一个流的迟到事件污染下一个流
// - 类型定义放在这里，useChat.ts 不再持 type

import { create } from 'zustand';

import type {
  AgentEvent,
  TaskPlanItem,
  TaskReviewEvent,
  TaskStatusEvent,
} from '../../shared/api';
import type { ToolCall } from '../../shared/lib/store';

/** 流式消息的临时覆盖层（'🤔 思考中…' + LLM 累积的 content/reasoning） */
export interface StreamingState {
  messageId: string;
  content: string;
  reasoning: string;
  state: AgentEvent['state'] | null;
  /** 阶段 4: 当前执行 agent 的 ID */
  currentAgentId: string | null;
  /** P2: 当前 ReAct 迭代轮次 */
  iteration: number;
}

/** 进度可视化 5 元组（与 useChat 内 TaskBoard 同字段，提取独立文件便于 store 引用） */
export interface TaskBoardState {
  runId: string;
  plan: TaskPlanItem[];
  statuses: Record<string, TaskStatusEvent>;
  progress?: {
    total: number;
    done: number;
    running: number;
    queued: number;
    failed: number;
  };
  dispatchedAt?: number | null;
  /** P0-6 (2026-08-20): reviewer 复核结论（每 run 至多一条，后到覆盖先到）。 */
  review?: TaskReviewEvent | null;
}

interface ChatStreamStoreState {
  streaming: StreamingState | null;
  streamingToolCalls: ToolCall[];
  taskBoard: TaskBoardState | null;

  // —— 流式生命周期 ——
  startStream: (
    messageId: string,
    opts?: { initialContent?: string; agentId?: string | null },
  ) => void;
  appendContent: (messageId: string, next: string) => void;
  replaceContent: (messageId: string, next: string) => void;
  appendReasoning: (messageId: string, next: string) => void;
  /** 更新 meta 字段（currentAgentId / iteration / state），不碰 content/reasoning */
  setStreamingMeta: (
    messageId: string,
    patch: Partial<Pick<StreamingState, 'state' | 'currentAgentId' | 'iteration'>>,
  ) => void;
  clearStream: (messageId: string) => void;

  // —— 工具调用 ——
  resetToolCalls: () => void;
  appendOrUpdateToolCall: (tc: ToolCall) => void;

  // —— 任务板 ——
  setTaskBoard: (board: TaskBoardState | null) => void;
  updateTaskBoard: (
    runId: string,
    updater: (prev: TaskBoardState | null) => TaskBoardState | null,
  ) => void;

  // —— 一锅端（reset / 测试清理 / 异常恢复） ——
  resetAll: () => void;
}

const initial = {
  streaming: null as StreamingState | null,
  streamingToolCalls: [] as ToolCall[],
  taskBoard: null as TaskBoardState | null,
};

export const useChatStreamStore = create<ChatStreamStoreState>((set) => ({
  ...initial,

  startStream: (messageId, opts) =>
    set({
      streaming: {
        messageId,
        content: opts?.initialContent ?? '',
        reasoning: '',
        state: 'thinking',
        currentAgentId: opts?.agentId ?? null,
        iteration: 0,
      },
      streamingToolCalls: [],
      taskBoard: null,
    }),

  appendContent: (messageId, next) =>
    set((prev) =>
      prev.streaming && prev.streaming.messageId === messageId
        ? { streaming: { ...prev.streaming, content: prev.streaming.content + next } }
        : prev,
    ),

  replaceContent: (messageId, next) =>
    set((prev) =>
      prev.streaming && prev.streaming.messageId === messageId
        ? { streaming: { ...prev.streaming, content: next } }
        : prev,
    ),

  appendReasoning: (messageId, next) =>
    set((prev) =>
      prev.streaming && prev.streaming.messageId === messageId
        ? { streaming: { ...prev.streaming, reasoning: prev.streaming.reasoning + next } }
        : prev,
    ),

  setStreamingMeta: (messageId, patch) =>
    set((prev) =>
      prev.streaming && prev.streaming.messageId === messageId
        ? { streaming: { ...prev.streaming, ...patch } }
        : prev,
    ),

  clearStream: (messageId) =>
    set((prev) =>
      prev.streaming && prev.streaming.messageId === messageId
        ? { streaming: null }
        : prev,
    ),

  resetToolCalls: () => set({ streamingToolCalls: [] }),

  appendOrUpdateToolCall: (tc) =>
    set((prev) => {
      const idx = tc.id ? prev.streamingToolCalls.findIndex((t) => t.id === tc.id) : -1;
      if (idx < 0) {
        return { streamingToolCalls: [...prev.streamingToolCalls, tc] };
      }
      const next = prev.streamingToolCalls.slice();
      next[idx] = { ...next[idx], ...tc };
      return { streamingToolCalls: next };
    }),

  setTaskBoard: (board) => set({ taskBoard: board }),

  updateTaskBoard: (_runId, updater) =>
    set((prev) => {
      const next = updater(prev.taskBoard);
      // updater 内部已经做了 runId 匹配；store 层不再二次校验以保留灵活性
      return { taskBoard: next };
    }),

  resetAll: () => set({ ...initial }),
}));