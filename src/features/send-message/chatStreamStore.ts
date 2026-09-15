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
// S2 键控改造（2026-09-06，对标 ZCode 多会话并行）：
// - 状态从"全局单槽"改为 `sessions: Record<sessionId, SessionStreamSlots>`
//   —— 每个会话独立的 streaming/toolCalls/taskBoard/todos 槽位。
//   会话 A 在后台流式时切到会话 B，B 的进度看 B 的槽位，互不覆盖；
//   侧边栏也可按会话聚合出运行态/进度徽章。
// - 所有 action 以 sessionId 为第一参数；messageId/runId 守卫逻辑不变，
//   只是守卫范围从"全局唯一流"收窄为"该会话内的流"。
// - /btw 侧问的伪会话 '__btw__' 天然获得独立槽位（此前与主流共享单槽,
//   btw 期间的 taskBoard 事件会污染主对话面板）。
//
// 设计：
// - 独立 zustand store，module-singleton，跨组件实例 / 跨路由保留
// - 每个 action 校验 messageId，避免上一个流的迟到事件污染下一个流
// - 类型定义放在这里，useChat.ts 不再持 type

import { create } from 'zustand';

import type {
  AgentEvent,
  SubagentLiveEvent,
  SubagentLiveState,
  TaskPlanItem,
  TaskReviewEvent,
  TaskStatusEvent,
  TodoItem,
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
    cancelled: number;
  };
  dispatchedAt?: number | null;
  /** P0-6 (2026-08-20): reviewer 复核结论（每 run 至多一条，后到覆盖先到）。 */
  review?: TaskReviewEvent | null;
  /**
   * live-events P0 (2026-09-06): 子任务实时执行态，按 task_id 索引。
   * 由 ``subagent_event`` 镜像事件喂给 reducer（useChat），任务树行内
   * 实时步骤 / 审批徽章 / 最近事件环形缓冲的唯一数据源。
   */
  live?: Record<string, SubagentLiveState>;
  /** live-events P1: 本 run 子代理审批模式（"ask" | "auto"，开关回显）。 */
  approvalMode?: 'ask' | 'auto';
}

/** live[task_id] 初始态 */
export function emptyLiveState(): SubagentLiveState {
  return { liveStep: null, waitingApproval: null, events: [] };
}

/** live 事件环形缓冲上限 —— 老事件从头丢弃。 */
export const LIVE_EVENT_BUFFER_SIZE = 20;

/**
 * 合并一条 ``subagent_event`` 镜像进 live 态（不可变，reducer 纯函数）。
 * 返回原引用当事件不属于该任务时;常规路径返回新对象供 React 浅比较。
 */
export function mergeLiveEvent(
  prev: SubagentLiveState | undefined,
  event: SubagentLiveEvent,
): SubagentLiveState {
  const base = prev ?? emptyLiveState();
  const events: SubagentLiveEvent[] = [...base.events, event].slice(
    -LIVE_EVENT_BUFFER_SIZE,
  );
  const next: SubagentLiveState = {
    liveStep: event.live_step ?? base.liveStep,
    waitingApproval: base.waitingApproval,
    events,
  };
  if (event.phase === 'approval_requested') {
    next.waitingApproval = event.tool_name ?? 'tool';
  } else if (event.phase === 'approval_resolved') {
    next.waitingApproval = null;
  }
  return next;
}

/** 单个会话的流式槽位（S2 键控） */
export interface SessionStreamSlots {
  streaming: StreamingState | null;
  streamingToolCalls: ToolCall[];
  taskBoard: TaskBoardState | null;
  // P1 todo 接线 (2026-08-21): todo_snapshot 全量快照（agent 自维护清单）。
  todos: TodoItem[];
}

const EMPTY_SLOTS: SessionStreamSlots = {
  streaming: null,
  streamingToolCalls: [],
  taskBoard: null,
  todos: [],
};

/** 读取某会话的槽位；无该会话（或 sessionId 为 null）时返回共享空槽位。
 *  共享引用保证 zustand 默认引用相等语义下"无流会话"的选择器结果稳定，
 *  不会触发无谓 re-render。 */
export function selectSessionSlots(
  state: { sessions: Record<string, SessionStreamSlots> },
  sessionId: string | null | undefined,
): SessionStreamSlots {
  if (sessionId == null) return EMPTY_SLOTS;
  return state.sessions[sessionId] ?? EMPTY_SLOTS;
}

interface ChatStreamStoreState {
  /** S2: sessionId → 该会话的流式槽位（并行会话各自独立） */
  sessions: Record<string, SessionStreamSlots>;

  // —— 流式生命周期（均以 sessionId 为第一参数） ——
  startStream: (
    sessionId: string,
    messageId: string,
    opts?: { initialContent?: string; agentId?: string | null },
  ) => void;
  appendContent: (sessionId: string, messageId: string, next: string) => void;
  replaceContent: (sessionId: string, messageId: string, next: string) => void;
  appendReasoning: (sessionId: string, messageId: string, next: string) => void;
  /**
   * 整体替换 streaming.reasoning —— 2026-09-02 修复引入。
   * 后端在每段 reasoning 流式末尾发一条 `state: 'reasoning_final'` 事件,
   * 携带 done_reasoning 全量(对齐持久化字段);前端必须 replace 而非 append,
   * 否则 deltas + final 双重累积会导致用户视觉上"思考过程重复两遍"。
   * 与已有 replaceContent 对称 — append 用于流式 delta,replace 用于收尾全量。
   */
  replaceReasoning: (sessionId: string, messageId: string, next: string) => void;
  /** 更新 meta 字段（currentAgentId / iteration / state），不碰 content/reasoning */
  setStreamingMeta: (
    sessionId: string,
    messageId: string,
    patch: Partial<Pick<StreamingState, 'state' | 'currentAgentId' | 'iteration'>>,
  ) => void;
  clearStream: (sessionId: string, messageId: string) => void;

  // —— 工具调用 ——
  resetToolCalls: (sessionId: string) => void;
  appendOrUpdateToolCall: (sessionId: string, tc: ToolCall) => void;

  // —— 任务板 ——
  setTaskBoard: (sessionId: string, board: TaskBoardState | null) => void;
  updateTaskBoard: (
    sessionId: string,
    runId: string,
    updater: (prev: TaskBoardState | null) => TaskBoardState | null,
  ) => void;

  // —— todo 清单（P1 接线） ——
  setTodos: (sessionId: string, todos: TodoItem[]) => void;

  // —— 会话删除时清理槽位，防 Map 泄漏 / 迟到事件复活死会话 ——
  clearSession: (sessionId: string) => void;

  // —— 一锅端（reset / 测试清理 / 异常恢复） ——
  resetAll: () => void;
}

type SessionSlotsDraft = Partial<SessionStreamSlots>;

function writeSlots(
  prev: Record<string, SessionStreamSlots>,
  sessionId: string,
  draft: SessionSlotsDraft,
): Record<string, SessionStreamSlots> {
  const slots = prev[sessionId] ?? EMPTY_SLOTS;
  return { ...prev, [sessionId]: { ...slots, ...draft } };
}

export const useChatStreamStore = create<ChatStreamStoreState>((set) => ({
  sessions: {},

  startStream: (sessionId, messageId, opts) =>
    set((prev) => ({
      sessions: writeSlots(prev.sessions, sessionId, {
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
        todos: [],
      }),
    })),

  appendContent: (sessionId, messageId, next) =>
    set((prev) => {
      const slots = selectSessionSlots(prev, sessionId);
      return slots.streaming && slots.streaming.messageId === messageId
        ? {
            sessions: writeSlots(prev.sessions, sessionId, {
              streaming: { ...slots.streaming, content: slots.streaming.content + next },
            }),
          }
        : prev;
    }),

  replaceContent: (sessionId, messageId, next) =>
    set((prev) => {
      const slots = selectSessionSlots(prev, sessionId);
      return slots.streaming && slots.streaming.messageId === messageId
        ? {
            sessions: writeSlots(prev.sessions, sessionId, {
              streaming: { ...slots.streaming, content: next },
            }),
          }
        : prev;
    }),

  appendReasoning: (sessionId, messageId, next) =>
    set((prev) => {
      const slots = selectSessionSlots(prev, sessionId);
      return slots.streaming && slots.streaming.messageId === messageId
        ? {
            sessions: writeSlots(prev.sessions, sessionId, {
              streaming: { ...slots.streaming, reasoning: slots.streaming.reasoning + next },
            }),
          }
        : prev;
    }),

  // 2026-09-02 bug fix: 与 replaceContent 对称, 用于替换 reasoning 全量。
  // 后端 reasoning_final 事件带 done_reasoning 全量 → 整体替换,不追加。
  replaceReasoning: (sessionId, messageId, next) =>
    set((prev) => {
      const slots = selectSessionSlots(prev, sessionId);
      return slots.streaming && slots.streaming.messageId === messageId
        ? {
            sessions: writeSlots(prev.sessions, sessionId, {
              streaming: { ...slots.streaming, reasoning: next },
            }),
          }
        : prev;
    }),

  setStreamingMeta: (sessionId, messageId, patch) =>
    set((prev) => {
      const slots = selectSessionSlots(prev, sessionId);
      return slots.streaming && slots.streaming.messageId === messageId
        ? {
            sessions: writeSlots(prev.sessions, sessionId, {
              streaming: { ...slots.streaming, ...patch },
            }),
          }
        : prev;
    }),

  clearStream: (sessionId, messageId) =>
    set((prev) => {
      const slots = selectSessionSlots(prev, sessionId);
      return slots.streaming && slots.streaming.messageId === messageId
        ? { sessions: writeSlots(prev.sessions, sessionId, { streaming: null }) }
        : prev;
    }),

  resetToolCalls: (sessionId) =>
    set((prev) => ({ sessions: writeSlots(prev.sessions, sessionId, { streamingToolCalls: [] }) })),

  appendOrUpdateToolCall: (sessionId, tc) =>
    set((prev) => {
      const slots = selectSessionSlots(prev, sessionId);
      const tcs = slots.streamingToolCalls;
      const idx = tc.id ? tcs.findIndex((t) => t.id === tc.id) : -1;
      const next = idx < 0 ? [...tcs, tc] : tcs.map((t, i) => (i === idx ? { ...t, ...tc } : t));
      return { sessions: writeSlots(prev.sessions, sessionId, { streamingToolCalls: next }) };
    }),

  setTaskBoard: (sessionId, board) =>
    set((prev) => ({ sessions: writeSlots(prev.sessions, sessionId, { taskBoard: board }) })),

  setTodos: (sessionId, todos) =>
    set((prev) => ({ sessions: writeSlots(prev.sessions, sessionId, { todos }) })),

  updateTaskBoard: (sessionId, _runId, updater) =>
    set((prev) => {
      const slots = selectSessionSlots(prev, sessionId);
      const next = updater(slots.taskBoard);
      // updater 内部已经做了 runId 匹配；store 层不再二次校验以保留灵活性
      return { sessions: writeSlots(prev.sessions, sessionId, { taskBoard: next }) };
    }),

  clearSession: (sessionId) =>
    set((prev) => {
      if (!(sessionId in prev.sessions)) return prev;
      const next = { ...prev.sessions };
      delete next[sessionId];
      return { sessions: next };
    }),

  resetAll: () => set({ sessions: {} }),
}));
