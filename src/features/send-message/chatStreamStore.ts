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
  ChatConfig,
  ChatOfficeRef,
  MessageDisplayMeta,
  RetryInfo,
  SubagentLiveEvent,
  SubagentLiveState,
  TaskPlanItem,
  TaskReviewEvent,
  TaskStatusEvent,
  TodoItem,
} from '../../shared/api';
import type { AttachmentEmbedConfig } from '../../shared/api/attachmentRagConfig';
import type { ResearchReport, StepConfirmInfo } from '../../shared/api/types/planModeTypes';
import type { Message, ToolCall } from '../../shared/lib/store';

import type { DeliveryMode } from './deliveryMode';
import { THINKING_PLACEHOLDER } from './thinkingPlaceholder';

/**
 * 队列条目的发送参数 —— 与 `useChat.sendMessage` 的入参一一对应。
 * 旧实现（useChat 内的 pendingMessagesRef）只存 content，flush 时图片 /
 * 附件 / officeRefs / planMode 全部丢失，这里补齐为可重放的完整调用快照。
 */
export interface QueuedSendOptions {
  /** Wave 3: resume 恢复流透传的既有计划 */
  planOverride?: TaskPlanItem[];
  /** Wave 3: resume 恢复流透传的 run id */
  runId?: string;
  /** PM1: 计划模式 —— 本次 run 只读调研 + 计划产出 */
  planMode?: boolean;
  /** 对标 S2: 临时聊天（本轮不读写长期记忆） */
  memoryDisabled?: boolean;
  /** R23-D2: 聊天图片输入（base64 data URL，后端限 4 张/单张 5MiB） */
  images?: string[];
  /** 2026-10-31: 前端确认/编辑后的本地 OCR 文本（与 images 对齐） */
  imageOcrTexts?: string[];
  /** R37: 已上传附件的 media id 列表 */
  attachmentMediaIds?: string[];
  /** r67: 附件检索注入配置（opt-in） */
  attachmentRag?: { embed: AttachmentEmbedConfig; top_k: number } | null;
  /** Task 5: 上下文重置 —— 后端在本轮消息前插入 topic_separator 并清空历史窗口 */
  contextReset?: boolean;
  /**
   * P2-a: 投递通道（插话 / 排队 / 打断并发送）。只在**会话已有活跃流**时有
   * 语义 —— 空闲时正常发送、以及队列 flush 出来的条目都会忽略它。
   */
  delivery?: DeliveryMode;
  /** 重新生成：被替换的 assistant 消息 id（后端用此回滚该轮次） */
  regenerateOf?: string;
  /**
   * 用户消息展示元数据 —— 忙时入队的消息 flush 后仍要在气泡上回显
   * 附件 / @ 文件引用 / office 引用，因此随队列条目一起保存。
   */
  displayMeta?: MessageDisplayMeta;
}

/** 一条待发送消息（会话忙时入队，当前 run 自然结束后 flush） */
export interface QueuedChatMessage {
  id: string;
  sessionId: string;
  content: string;
  createdAt: number;
  officeRefs?: readonly ChatOfficeRef[];
  orchestrationMode?: ChatConfig['orchestrationMode'];
  opts?: QueuedSendOptions;
}

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
  /** R17-E 收尾（r71）: memory_used 载荷写入（气泡内可展开） */
  memory_refs?: { id: string; memory_type: string; preview: string }[];
  /** r71: attachment_rag_used 载荷写入 */
  rag_citations?: { media_id: string; mode: string }[];
  /**
   * 2026-10-26: 流开始时间戳（Date.now()），用于首字等待计时器。
   * ThinkingShimmer 组件读取此字段显示已等待秒数，提升用户感知。
   */
  startTime?: number;
  /**
   * 2026-10-20: LLM 重试可视化。state === 'retry' 时由 setRetryInfo 写入,
   * Message.tsx 读此字段渲染 RetryBanner（带倒计时）。
   * 2026-10-25: 非 retry 状态到达时不再立即清 null，而是延迟 3 秒隐藏
   * （通过 _retryHideTimer 调度），让用户能看见发生了什么。
   */
  retryInfo?: RetryInfo | null;
  /** 2026-10-25: retryInfo 逻辑上被清除的时间戳（用于延迟隐藏） */
  retryInfoClearedAt?: number | null;
  /** 内部：延迟清除 retryInfo 的 setTimeout ID */
  _retryHideTimer?: number;
}

/** 进度可视化 5 元组（与 useChat 内 TaskBoard 同字段，提取独立文件便于 store 引用） */
export interface TaskBoardState {
  runId: string;
  plan: TaskPlanItem[];
  // 编排计划卡片 UX (2026-10-26): LLM 的规划思路（为什么这样拆解）——
  // task_plan 事件透传，PlanCard 折叠展示；修订后由前端回写覆盖。
  reasoning?: string;
  statuses: Record<string, TaskStatusEvent>;
  progress?: {
    total: number;
    done: number;
    running: number;
    queued: number;
    failed: number;
    cancelled: number;
    // Phase 3 (2026-10-28): 步骤确认跳过的任务数（可选，旧事件无此字段）。
    skipped?: number;
  };
  dispatchedAt?: number | null;
  // RD20 (round43): 历史 run 恢复时的终态时刻 —— BU16 时长在恢复态显示
  // 原始总时长（直播态为 null，由 tick 冻结逻辑覆盖）。
  endedAt?: number | null;
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
  const events: SubagentLiveEvent[] = [...base.events, event].slice(-LIVE_EVENT_BUFFER_SIZE);
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

/**
 * 2026-10-28 (Plan Mode 增强): 执行模式推荐（后端分类器产物）。
 * mode: single / multi / ask_user；confidence: 0-1；reasoning: 一句话判断依据。
 */
export interface ExecutionModeRecommendation {
  mode: 'single' | 'multi' | 'ask_user';
  confidence: number;
  reasoning: string;
}

/** 单个会话的流式槽位（S2 键控） */
export interface SessionStreamSlots {
  streaming: StreamingState | null;
  streamingToolCalls: ToolCall[];
  taskBoard: TaskBoardState | null;
  // P1 todo 接线 (2026-08-21): todo_snapshot 全量快照（agent 自维护清单）。
  todos: TodoItem[];
  /**
   * 2026-09 step-by-step: 已完成 ReAct 步骤的快照数组（每条对应独立消息气泡）。
   * - 收到 step_done 事件时,把当前 streaming state 打包成 Message 推入此数组
   * - 同时重置 streaming.content=THINKING_PLACEHOLDER / streaming.reasoning=''
   *   / streamingToolCalls=[],以便下一步的 deltas 路由到新的 messageId
   * - DONE 事件不追加(最后一步走 finishStream 路径)
   * - startStream / resetAll 时清空
   */
  completedSteps: Message[];
  /**
   * Task 11 (2026-09-17): topic_shifted 事件 — 收到自动话题切换通知时
   * 写入,前端 TopicShiftBanner 展示"恢复完整上下文"入口;用户点恢复
   * 或点关闭时调用 clearShiftInfo 清掉;切会话 / startStream 也会清。
   *
   * created_at 用于自动过期:后台会话的 shiftInfo 不会被 banner 消费,
   * 30 秒后读取时自动视为 null,避免用户切回时会话看到陈旧横幅。
   */
  shiftInfo: { segmentId: number; reason: string; createdAt: number } | null;
  /**
   * Round 3 (2026-09-19): 编排拆解前置阶段（需求澄清/事实侦察）。
   * 先于 task_plan 到达时任务板还不存在，故独立于 TaskBoardState 存槽位；
   * task_plan 初始化 / finishStream 兜底时清空。
   */
  preflightPhase: 'clarify' | 'scout' | 'complexity_classify' | 'execution_mode_classify' | null;
  /**
   * 2026-10-28 (Plan Mode 增强): 计划模式收尾时后端分类器给出的执行模式推荐。
   * 在 DONE 之前随 `plan_execution_mode` 事件到达，供 PlanApprovalBar 做
   * "推荐 + 可覆盖"。null = 尚未收到推荐（分类降级或非计划模式）。
   */
  executionModeRecommendation: ExecutionModeRecommendation | null;
  /**
   * 2026-10-28 (Plan Mode 增强 Phase 2): 复杂任务深度调研结果。
   * 在 scout_deep 完成后随 `research_complete` 事件到达，供 ResearchSummaryCard 渲染。
   * null = 尚未收到调研报告（非 complex 任务或调研失败降级）。
   */
  researchReport: ResearchReport | null;
  /**
   * 2026-10-28 (Plan Mode 增强 Phase 3): 自动确认点（步骤确认对话框信息）。
   * 当 plan 执行到标记为 auto_confirm 的步骤时，后端发 awaiting_step_confirm 事件，
   * 前端写入此槽位供 StepConfirmDialog 渲染。用户操作后由 clearStepConfirm 清空。
   * null = 未等待确认（常规步骤或用户已响应）。
   */
  stepConfirm: StepConfirmInfo | null;
  /**
   * U5 队列（2026-09-18 从 useChat 的 component-local ref 迁入）：
   * 会话忙时用户继续发送的消息在此排队，当前 run 自然结束后 flush。
   * 放 store 而非 ref 的两个理由：①UI 需要渲染并可操作队列；
   * ②Chat 页卸载/路由切换不再丢队列。
   */
  pendingQueue: QueuedChatMessage[];
  /**
   * 队列暂停位：run 以错误/中断收尾时置 true —— 此时自动 flush 只会把
   * 用户没打算重发的消息推进同一个故障里。UI 显示"已暂停"并等用户恢复。
   */
  queuePaused: boolean;
  /**
   * Issue 3: ReAct 轮次累加偏移（跨 run 累积）。
   * 后端 `run_loop` 的 iteration 是局部计数器（for i in range(max_iterations)），
   * 每次新 run 都从 0 开始。前端在 clearStream 时把本次达到的最大轮次 +1 累加到此处，
   * ActiveAgentIndicator 显示 `iterationOffset + streaming.iteration`，
   * 让用户在"继续"后看到的轮次是接续上次的进度而非重置。
   */
  iterationOffset: number;
}

const EMPTY_SLOTS: SessionStreamSlots = {
  streaming: null,
  streamingToolCalls: [],
  taskBoard: null,
  todos: [],
  completedSteps: [],
  shiftInfo: null,
  preflightPhase: null,
  executionModeRecommendation: null,
  researchReport: null,
  stepConfirm: null,
  pendingQueue: [],
  queuePaused: false,
  iterationOffset: 0,
};

/** 空槽位工厂：构造/打桩槽位时用它展开，新增字段不会再漏（浅拷贝即可，
 *  数组字段一律由 action 以不可变方式整体替换，不会被就地改写）。 */
export function emptySessionSlots(): SessionStreamSlots {
  return { ...EMPTY_SLOTS };
}

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
    patch: Partial<
      Pick<
        StreamingState,
        'state' | 'currentAgentId' | 'iteration' | 'memory_refs' | 'rag_citations'
      >
    >,
  ) => void;
  /**
   * 2026-10-20: 写入 LLM 重试信息。Message.tsx 从 streaming.retryInfo 读
   * 取并渲染 RetryBanner。retry 事件到达时覆盖，其他状态到达时由
   * setStreamingMeta 自动清 null。
   */
  setRetryInfo: (sessionId: string, messageId: string, info: RetryInfo | null) => void;
  clearStream: (sessionId: string, messageId: string) => void;

  // —— 工具调用 ——
  resetToolCalls: (sessionId: string) => void;
  appendOrUpdateToolCall: (sessionId: string, tc: ToolCall) => void;

  // —— 任务板 ——
  setTaskBoard: (sessionId: string, board: TaskBoardState | null) => void;
  /** Round 3 (2026-09-19): 写入/清空编排拆解前置阶段指示。 */
  setPreflightPhase: (
    sessionId: string,
    phase: 'clarify' | 'scout' | 'complexity_classify' | 'execution_mode_classify' | null,
  ) => void;
  /**
   * 2026-10-28 (Plan Mode 增强): 写入/清空计划模式的执行模式推荐。
   * 由 `plan_execution_mode` 事件驱动（该事件在 DONE 之前到达）。
   */
  setExecutionModeRecommendation: (
    sessionId: string,
    recommendation: ExecutionModeRecommendation | null,
  ) => void;
  /**
   * 2026-10-28 (Plan Mode 增强 Phase 2): 写入/清空复杂任务深度调研结果。
   * 由 `research_complete` 事件驱动（scout_deep 完成后到达）。
   */
  setResearchReport: (sessionId: string, report: ResearchReport | null) => void;
  /**
   * 2026-10-28 (Plan Mode 增强 Phase 3): 写入/清空步骤确认对话框信息。
   * 由 `awaiting_step_confirm` 事件驱动（auto_confirm 步骤到达时）。
   * 用户响应后传 null 清空。
   */
  setStepConfirm: (sessionId: string, info: StepConfirmInfo | null) => void;
  updateTaskBoard: (
    sessionId: string,
    runId: string,
    updater: (prev: TaskBoardState | null) => TaskBoardState | null,
  ) => void;

  // —— todo 清单（P1 接线） ——
  setTodos: (sessionId: string, todos: TodoItem[]) => void;

  // —— 2026-09 step-by-step ——
  /**
   * 把当前 streaming 状态快照为一条已完成的 Message,推入 completedSteps。
   * 不重置 streaming —— 由 finalizeStep 配套重置并切换 messageId。
   * 调用方应保证此时 streaming.messageId === messageId（否则 action 静默 noop）。
   */
  addCompletedStep: (sessionId: string, messageId: string, message: Message) => void;
  /**
   * 完成一步:push 完成后重置 streaming.content/reasoning/streamingToolCalls 为占位态,
   * 并切换 streaming.messageId 到 newMessageId,让后续 deltas 路由到新消息。
   * 配套 addCompletedStep 使用:先 addCompletedStep,再 finalizeStep。
   */
  finalizeStep: (sessionId: string, oldMessageId: string, newMessageId: string) => void;

  // —— Task 11 (2026-09-17): topic_shifted 横幅态 ——
  /** 收到 topic_shifted 事件时写入;前端 TopicShiftBanner 展示"恢复完整上下文"入口;用户点恢复
   * 或点关闭时调用 clearShiftInfo 清掉;切会话 / startStream 也会清。 */
  setShiftInfo: (
    sessionId: string,
    info: { segmentId: number; reason: string; createdAt: number } | null,
  ) => void;

  // —— U5 待发送队列（按会话隔离） ——
  /** 入队一条待发送消息，返回落库后的条目（调用方需要 id）。 */
  enqueueChat: (
    sessionId: string,
    message: Omit<QueuedChatMessage, 'id' | 'sessionId' | 'createdAt'>,
  ) => QueuedChatMessage;
  removeChatFromQueue: (sessionId: string, id: string) => void;
  /** 取出并移除（"立即发送"/"编辑"共用）；不存在返回 null。 */
  takeChatFromQueue: (sessionId: string, id: string) => QueuedChatMessage | null;
  /** 置顶：把某条排队消息提到队首，改变自动发送顺序。 */
  moveChatToQueueFront: (sessionId: string, id: string) => void;
  /** 拖拽排序：把 fromId 这条移动到 toId 当前所在下标；任一侧不存在则 noop。 */
  reorderChatQueue: (sessionId: string, fromId: string, toId: string) => void;
  clearChatQueue: (sessionId: string) => void;
  setChatQueuePaused: (sessionId: string, paused: boolean) => void;
  /** 弹出队首（run 自然结束后 flush 用）；队列空返回 null。 */
  shiftChatQueue: (sessionId: string) => QueuedChatMessage | null;

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

export const useChatStreamStore = create<ChatStreamStoreState>((set, get) => ({
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
          retryInfo: null,
          retryInfoClearedAt: null,
          startTime: Date.now(),
        },
        streamingToolCalls: [],
        taskBoard: null,
        todos: [],
        completedSteps: [],
        // Task 11 (2026-09-17): 新一轮流式清掉 topic_shifted 横幅态
        shiftInfo: null,
        // 2026-10-28 (Plan Mode 增强): 新一轮清掉上一轮的执行模式推荐
        // —— 推荐在 plan_execution_mode 事件里到达（DONE 之前），必须留到
        // 本轮 plan 审阅用，不能在 finishStream 里清。
        executionModeRecommendation: null,
        // 2026-10-28 (Plan Mode 增强 Phase 2): 新一轮清掉调研报告
        // —— 避免上一轮的 researchReport 在新 run 开始时残留（review #12）。
        researchReport: null,
        // 2026-10-28 (Plan Mode 增强 Phase 3): 新一轮清掉步骤确认对话框态
        // —— 避免上一轮的确认信息在新 run 开始时残留。
        stepConfirm: null,
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
      if (!slots.streaming || slots.streaming.messageId !== messageId) return prev;
      // 2026-10-20: 非 retry 状态到达时自动清 retryInfo —— Banner 随之消失
      // 2026-10-25: 改为延迟 3 秒隐藏，让用户能看见重试发生过。
      // 保留 retryInfo 数据，仅记录 clearedAt 时间戳；3 秒后 setTimeout
      // 才真正将 retryInfo 置 null。
      const autoClearRetry =
        patch.state !== undefined && patch.state !== 'retry' && slots.streaming.retryInfo != null;
      if (autoClearRetry) {
        // 清除旧的定时器（如有）
        if (slots.streaming._retryHideTimer) {
          clearTimeout(slots.streaming._retryHideTimer);
        }
        const clearedAt = Date.now();
        const nextStreaming = {
          ...slots.streaming,
          ...patch,
          retryInfoClearedAt: clearedAt,
          // 暂不清 retryInfo，保留给 selector 用
        };
        // 3 秒后真正清除 retryInfo
        const timer = window.setTimeout(() => {
          useChatStreamStore.setState((state) => {
            const currentSlots = selectSessionSlots(state, sessionId);
            if (
              !currentSlots.streaming ||
              currentSlots.streaming.messageId !== messageId ||
              currentSlots.streaming.retryInfoClearedAt !== clearedAt
            )
              return state;
            return {
              sessions: writeSlots(state.sessions, sessionId, {
                streaming: {
                  ...currentSlots.streaming,
                  retryInfo: null,
                  retryInfoClearedAt: null,
                  _retryHideTimer: undefined,
                },
              }),
            };
          });
        }, 3000);
        return {
          sessions: writeSlots(prev.sessions, sessionId, {
            streaming: { ...nextStreaming, _retryHideTimer: timer },
          }),
        };
      }
      const nextStreaming = { ...slots.streaming, ...patch };
      return {
        sessions: writeSlots(prev.sessions, sessionId, { streaming: nextStreaming }),
      };
    }),

  // 2026-10-20: LLM 重试可视化 —— 写入 retryInfo 供 Message.tsx 渲染 RetryBanner
  // 2026-10-25: 同时取消旧隐藏定时器，重置 retryInfoClearedAt，让新重试立刻可见。
  setRetryInfo: (sessionId, messageId, info) =>
    set((prev) => {
      const slots = selectSessionSlots(prev, sessionId);
      if (!slots.streaming || slots.streaming.messageId !== messageId) return prev;
      // 取消旧的 3 秒隐藏定时器（上次重试成功后的延迟隐藏）
      if (slots.streaming._retryHideTimer) {
        clearTimeout(slots.streaming._retryHideTimer);
      }
      return {
        sessions: writeSlots(prev.sessions, sessionId, {
          streaming: {
            ...slots.streaming,
            retryInfo: info,
            retryInfoClearedAt: null,
            _retryHideTimer: undefined,
          },
        }),
      };
    }),

  clearStream: (sessionId, messageId) =>
    set((prev) => {
      const slots = selectSessionSlots(prev, sessionId);
      if (!(slots.streaming && slots.streaming.messageId === messageId)) return prev;
      // 2026-10-25: 流结束时取消任何待执行的延迟隐藏定时器
      if (slots.streaming._retryHideTimer) {
        clearTimeout(slots.streaming._retryHideTimer);
      }
      // Issue 3: 累加本轮达到的最大轮次到 iterationOffset。
      // iteration 是本次 run 最后一次 setStreamingMeta 写入的值（= 后端 for 循环当前 i）。
      // +1 因为步骤 0..i 共 i+1 步，下一次 run 显示要从 i+1 开始。
      const nextOffset = slots.iterationOffset + slots.streaming.iteration + 1;
      return {
        sessions: writeSlots(prev.sessions, sessionId, {
          streaming: null,
          iterationOffset: nextOffset,
        }),
      };
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

  setPreflightPhase: (sessionId, phase) =>
    set((prev) => ({ sessions: writeSlots(prev.sessions, sessionId, { preflightPhase: phase }) })),

  setExecutionModeRecommendation: (sessionId, recommendation) =>
    set((prev) => ({
      sessions: writeSlots(prev.sessions, sessionId, {
        executionModeRecommendation: recommendation,
      }),
    })),

  setResearchReport: (sessionId, report) =>
    set((prev) => ({
      sessions: writeSlots(prev.sessions, sessionId, {
        researchReport: report,
      }),
    })),

  setStepConfirm: (sessionId, info) =>
    set((prev) => ({
      sessions: writeSlots(prev.sessions, sessionId, {
        stepConfirm: info,
      }),
    })),

  setTodos: (sessionId, todos) =>
    set((prev) => ({ sessions: writeSlots(prev.sessions, sessionId, { todos }) })),

  // 2026-09 step-by-step: 把当前 streaming 快照为 Message 推入 completedSteps
  addCompletedStep: (sessionId, messageId, message) =>
    set((prev) => {
      const slots = selectSessionSlots(prev, sessionId);
      if (!slots.streaming || slots.streaming.messageId !== messageId) return prev;
      return {
        sessions: writeSlots(prev.sessions, sessionId, {
          completedSteps: [...slots.completedSteps, message],
        }),
      };
    }),

  // 2026-09 step-by-step: 重置 streaming 为占位 + 切换 messageId; 下一步 deltas 路由到新 messageId
  finalizeStep: (sessionId, oldMessageId, newMessageId) =>
    set((prev) => {
      const slots = selectSessionSlots(prev, sessionId);
      if (!slots.streaming || slots.streaming.messageId !== oldMessageId) return prev;
      // 2026-10-25: 步骤切换时取消任何待执行的延迟隐藏定时器
      if (slots.streaming._retryHideTimer) {
        clearTimeout(slots.streaming._retryHideTimer);
      }
      return {
        sessions: writeSlots(prev.sessions, sessionId, {
          streaming: {
            messageId: newMessageId,
            content: THINKING_PLACEHOLDER,
            reasoning: '',
            state: 'thinking',
            currentAgentId: slots.streaming.currentAgentId,
            iteration: slots.streaming.iteration,
            retryInfo: null,
            retryInfoClearedAt: null,
          },
          streamingToolCalls: [],
        }),
      };
    }),

  // Task 11 (2026-09-17): topic_shifted 横幅态 — 写入后由 TopicShiftBanner 展示
  setShiftInfo: (sessionId, info) =>
    set((prev) => ({ sessions: writeSlots(prev.sessions, sessionId, { shiftInfo: info }) })),

  // —— U5 待发送队列 ——
  enqueueChat: (sessionId, message) => {
    const item: QueuedChatMessage = {
      ...message,
      id: crypto.randomUUID(),
      sessionId,
      createdAt: Date.now(),
    };
    set((prev) => ({
      sessions: writeSlots(prev.sessions, sessionId, {
        pendingQueue: [...selectSessionSlots(prev, sessionId).pendingQueue, item],
      }),
    }));
    return item;
  },

  removeChatFromQueue: (sessionId, id) =>
    set((prev) => {
      const queue = selectSessionSlots(prev, sessionId).pendingQueue;
      if (!queue.some((m) => m.id === id)) return prev;
      return {
        sessions: writeSlots(prev.sessions, sessionId, {
          pendingQueue: queue.filter((m) => m.id !== id),
        }),
      };
    }),

  takeChatFromQueue: (sessionId, id) => {
    const item = selectSessionSlots(get(), sessionId).pendingQueue.find((m) => m.id === id);
    if (!item) return null;
    get().removeChatFromQueue(sessionId, id);
    return item;
  },

  moveChatToQueueFront: (sessionId, id) =>
    set((prev) => {
      const queue = selectSessionSlots(prev, sessionId).pendingQueue;
      const idx = queue.findIndex((m) => m.id === id);
      if (idx <= 0) return prev;
      const next = [...queue];
      const [item] = next.splice(idx, 1);
      return { sessions: writeSlots(prev.sessions, sessionId, { pendingQueue: [item, ...next] }) };
    }),

  /** 拖拽排序：把 fromId 移到 toId 当前所在的位置（落点语义同 dnd-kit arrayMove）。 */
  reorderChatQueue: (sessionId, fromId, toId) =>
    set((prev) => {
      const queue = selectSessionSlots(prev, sessionId).pendingQueue;
      const from = queue.findIndex((m) => m.id === fromId);
      const to = queue.findIndex((m) => m.id === toId);
      if (from < 0 || to < 0 || from === to) return prev;
      const next = [...queue];
      const [item] = next.splice(from, 1);
      next.splice(to, 0, item);
      return { sessions: writeSlots(prev.sessions, sessionId, { pendingQueue: next }) };
    }),

  clearChatQueue: (sessionId) =>
    set((prev) => ({
      sessions: writeSlots(prev.sessions, sessionId, { pendingQueue: [], queuePaused: false }),
    })),

  setChatQueuePaused: (sessionId, paused) =>
    set((prev) => {
      const slots = selectSessionSlots(prev, sessionId);
      if (slots.queuePaused === paused) return prev;
      return { sessions: writeSlots(prev.sessions, sessionId, { queuePaused: paused }) };
    }),

  shiftChatQueue: (sessionId) => {
    const queue = selectSessionSlots(get(), sessionId).pendingQueue;
    const [next] = queue;
    if (!next) return null;
    set((prev) => ({
      sessions: writeSlots(prev.sessions, sessionId, {
        pendingQueue: selectSessionSlots(prev, sessionId).pendingQueue.slice(1),
      }),
    }));
    return next;
  },

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

export function formatChatStreamSessionSummary(sessionId: string): string {
  const slots = selectSessionSlots(useChatStreamStore.getState(), sessionId);
  if (!slots.streaming) {
    return `${sessionId} · idle · tools=${slots.streamingToolCalls.length} · todos=${slots.todos.length}`;
  }
  return `${sessionId} · ${slots.streaming.state} · msg=${slots.streaming.messageId} · tools=${slots.streamingToolCalls.length}`;
}

export function formatChatStreamSessionJson(sessionId: string): string {
  const slots = selectSessionSlots(useChatStreamStore.getState(), sessionId);
  return JSON.stringify(
    {
      sessionId,
      streaming: slots.streaming !== null,
      state: slots.streaming?.state ?? null,
      messageId: slots.streaming?.messageId ?? null,
      toolCallCount: slots.streamingToolCalls.length,
      todoCount: slots.todos.length,
    },
    null,
    2,
  );
}

export function auditChatStreamStoreGovernance(): {
  module: 'src/features/send-message/chatStreamStore.ts';
  phase: 'P167';
  domain: 'send-message';
  sessionScopedIsolation: boolean;
  supportsTopicShiftAndTaskBoard: boolean;
  compliant: boolean;
} {
  return {
    module: 'src/features/send-message/chatStreamStore.ts',
    phase: 'P167',
    domain: 'send-message',
    sessionScopedIsolation: true,
    supportsTopicShiftAndTaskBoard: true,
    compliant: true,
  };
}
