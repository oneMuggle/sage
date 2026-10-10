import type { LLMErrorResponse } from '../../lib/errorMapping';

import type { OfficeDocType } from './officeDocTypes';

/**
 * Sage API - 类型定义
 */


// ==================== Session & Message 类型 ====================

export interface Session {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
  last_message_at: number | null;
  message_count: number;
  is_pinned: boolean;
  metadata?: Record<string, unknown>;
  /** M4: 分叉源会话 id（非分叉会话为 null），侧栏 fork 徽标依赖此字段 */
  fork_root?: string | null;
  /** M4: 分叉点消息 id（源会话中的 id）；null = 分叉到源会话末尾 */
  forked_at_message_id?: string | null;
  /** P0-4 (UI 优化方案 2026-09-13): 最后一条 user/assistant 消息预览(截断 80 字符) */
  last_message_preview?: string | null;
}

/** M4: POST /sessions/{id}/compact 响应 */
export interface SessionCompactResult {
  ok: boolean;
  /** 实际执行了压缩时为 true；低于地板时为 false（附 reason） */
  compacted?: boolean;
  /** 未压缩原因：below_message_floor | below_token_threshold */
  reason?: string;
  /** 失败原因：llm_not_configured | compaction_failed */
  error?: string;
  message?: string;
  before: number;
  after: number;
  removed: number;
}

/** R17-A2: GET /sessions/{id}/lineage 归档条目（压缩前缀派生的归档会话） */
export interface LineageArchive {
  archive_session_id: string;
  title: string;
  message_count: number;
  /** epoch ms；后端缺省时为 null */
  archived_at: number | string | null;
  /** 归档原因：compaction_prefix 等 */
  reason?: string | null;
}

/** R17-A2: GET /sessions/{id}/lineage 响应（archives 新→旧） */
export interface SessionLineage {
  session_id: string;
  archives: LineageArchive[];
}

/** Task 11 (2026-09-17): POST /sessions/{id}/segments/retreat 响应 */
export interface SessionRetreatResult {
  /** true = 成功删除了一个 separator 并 merge segments；false = 无可删的 separator */
  ok: boolean;
}

/** U18: POST /sessions/{id}/export 响应（JSON 信封，html 为自包含文档文本） */
export interface SessionExportResult {
  /** 自包含导出 HTML 全文（内联 CSS/JS/marked/highlight.js，离线可开） */
  html: string;
  /** 建议下载文件名，如 sage-session-<8位id>-<时间戳>.html */
  filename: string;
  session_id: string;
  message_count: number;
  /** 实际生效主题：auto / dark / light */
  theme: string;
}

export interface SessionWorkspaceBinding {
  sessionId: string;
  workspacePath: string;
  generation: number;
  activatedAt: number;
  revokedAt: number | null;
}

export type WorkspaceSearchKind =
  | 'file'
  | 'office-ppt'
  | 'office-word'
  | 'office-excel'
  | 'office-pdf';

export interface WorkspaceSearchResult {
  name: string;
  kind: WorkspaceSearchKind;
  docType: OfficeDocType | null;
  docId: string | null;
  sizeBytes: number;
  needsImport: boolean;
  sourcePath: string | null;
}

export interface WorkspaceSearchResponse {
  results: WorkspaceSearchResult[];
  total: number;
}

export interface ChatOfficeRef {
  docId: string;
  /**
   * B4 (office-p0): widened to include 'pdf' — the backend chat_refs
   * DocTypeLiteral accepts pdf refs (OfficeToolService.read dispatches
   * read_pdf) and the workspace search no longer coalesces managed pdf
   * docs to the plain-file path. Must stay in sync with
   * widgets/chat InputCard.OfficeRefChipType.
   */
  docType: 'ppt' | 'word' | 'excel' | 'pdf';
  filename: string;
}

export interface WorkspaceRevokeResponse {
  revoked: boolean;
  generation: number;
}

export interface Message {
  id: string;
  session_id: string;
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  created_at: number;
  model?: string;
  provider?: string;
  /**
   * wire 上是 JSON 字符串 (session_repo 原样存取, 不做 parse), 流式路径
   * 是数组 —— 消费方必须双态兼容 (见 Message.tsx 的归一化)。
   */
  tool_calls?: ToolCall[] | string | null;
  tool_call_id?: string;
  /** 2026-09 step-by-step: assistant 行的步序号（0 起；多步 run 时每步一行）。 */
  step_index?: number | null;
  /** alpha.36 (Bug #4): 同一 message 行内携带的 LLM 推理过程（持久化在 DB）。 */
  reasoning_content?: string | null;
  /** Task 5 (2026-09-17): 消息子类型 —— 'topic_separator' 渲染为分隔线。 */
  subtype?: string | null;
  /** R81: r71 附件检索溯源（get_messages 回读；流式经 AgentEvent.citations）。 */
  rag_citations?: RagCitation[] | null;
  /** R81: 工具命中来源（web/wiki/MCP），终稿 assistant 行落库回读。 */
  sources?: MessageSource[] | null;
}

/** R81: 统一参考来源条目 —— backend/chat/sources_extractor.py 的提取产物。 */
export interface MessageSource {
  /** R86: 新增 'memory' —— @memory: 实体引用命中（渲染进记忆分组）。 */
  kind: 'web' | 'wiki' | 'tool' | 'memory';
  title?: string;
  url?: string;
  snippet?: string;
  query?: string;
  path?: string;
  score?: number | null;
  server?: string;
  tool?: string;
  preview?: string;
}

/** R81: 附件检索溯源（r71，原 inline 形状收敛为此类型）。 */
export interface RagCitation {
  media_id: string;
  filename?: string;
  mode: string;
  chunks?: { index: number; score: number }[];
}

export interface ToolCall {
  name: string;
  args: Record<string, unknown>;
  result?: string;
}

export interface ChatRequest {
  session_id: string;
  message: string;
}

export interface ChatResponse {
  message: Message;
  session?: Session;
}

// ==================== Agent 流式事件 (PR-6) ====================

/** Agent 状态机 — 与后端 backend.core.legacy.agent_state.AgentState 一致 */
export type AgentState =
  | 'idle'
  | 'thinking'
  | 'reasoning' // 新增：携带 LLM 思考/推理过程内容
  | 'reasoning_delta' // 新增：reasoning 增量事件（流式输出）
  | 'reasoning_final' // 2026-09-02: reasoning 流末尾发的全量对齐事件,前端 replace
  | 'acting'
  | 'permission_request' // M1: 工具审批卡点 — 等待用户批准/拒绝
  | 'ask_user_question' // M2 part B: AskUserQuestion 卡点 — 等待用户选择/填写
  | 'suspended' // A4 Suspend-Resume: producer 主动让出, 等 wake 触发下一轮 (2026-09 补齐, 与后端 chat_stream_registry 一致)
  | 'observing'
  | 'content_delta'
  | 'done'
  | 'failed'
  // 2026-09 step-by-step: 每次 ReAct 迭代结束（OBSERVING 之后）由后端产出,
  // 前端据此把当前 streaming 气泡快照为已完成 step + 准备下一步占位。
  // win7: 后端枚举暂未产出 step_done,类型先行对齐 main（r112 全态锁定测试需要）。
  | 'step_done'
  // Multi-Agent Orchestration (2026-08-11)
  | 'task_plan'
  | 'task_status'
  // 进度可视化 P0-2 (2026-08-12): 整盘概览事件,在 task_plan 之后立刻
  // 推送一次,前端 taskBoard 渲染"已拆解为 N 个子任务"头部信息时不必
  // 等待 subtask 状态切换就能拿到 total。后续 5 元组也可由前端 reducer
  // 实时从 task_status 聚合,本事件只承担初始化职责。
  | 'task_progress'
  // Wave 2 (2026-08-14): reviewer 复核结论事件,见 TaskReviewEvent。
  | 'task_review'
  // P1 todo 接线 (2026-08-21): agent 任务清单全量快照,与 llmStream.ts 双处一致。
  | 'todo_snapshot'
  // live-events P0 (2026-09-06): 子代理内部事件投影镜像(工具调用/结果/
  // 审批/提问/失败),见 SubagentLiveState。不进消息气泡,进任务板 live 态。
  | 'subagent_event'
  // live-events P1 (2026-09-06): run 级子代理审批模式切换回显(ask|auto)。
  | 'approval_mode'
  // S7 (2026-09-06): 工具落库产物后经活跃流推送的事件,载荷见 AgentEvent.artifact。
  | 'artifact_created'
  // R17-E: 记忆召回展示 —— L13 注入记忆上下文后推送本次命中条目,
  // 载荷见 AgentEvent.memories。
  | 'memory_used'
  // R38 (2026-09-18): 技能激活展示 —— A16 自动激活或显式 /skill 调用后
  // 推送本次激活的技能列表,载荷见 AgentEvent.skills。
  | 'skill_activated'
  // R38 (2026-09-18): 自动上下文压缩展示 —— M4 达到阈值触发压缩后推送
  // 压缩统计,载荷见 AgentEvent.compact。
  | 'compact_triggered'
  // TM2 (DSH 对标 R11): 上下文水位 —— producer 装配请求后推送确定性
  // 计量(总量/分项/预算/pressure 0-1),载荷见 AgentEvent.context_pressure。
  | 'context_pressure'
  // Task 10 (2026-09-17): 自动话题检测 — 切换 segment 时由 producer 推送。
  | 'topic_shifted'
  // Round 3 (2026-09-19): 编排拆解前置进度（需求澄清/事实侦察）,
  // 载荷见 AgentEvent.preflight_phase。先于 task_plan 到达。
  | 'orch_preflight'
  // r71: 附件检索注入溯源（引用块在气泡内可展开）,
  // 载荷见 AgentEvent.citations。
  | 'attachment_rag_used'
  // right-panel R5 (2026-09-19): 写文件工具落盘后经活跃流推送的变更信号,
  // 前端据此防抖刷新右侧变更列表,载荷见 AgentEvent.change。
  | 'workspace_changed'
  // R81: 统一参考来源 —— 检索类工具命中（web/wiki/MCP）在 done 前
  // 一次性推送, 载荷见 AgentEvent.sources。
  | 'sources_used';

/**
 * TM2 (DSH 对标 R11): 上下文水位计量快照 —— 随 `state: 'context_pressure'`
 * 流事件下发（backend/chat/token_meter.py ContextPressure.to_dict()）。
 */
export interface ContextPressurePayload {
  total_tokens: number;
  budget_tokens: number;
  /** 0-1，已封顶；≥0.8 红 / ≥0.6 琥珀 */
  pressure: number;
  by_role: Record<string, number>;
  estimator: string;
}

/**
 * 工具审批请求 — M1 工具安全加固。
 *
 * 由后端 ApprovalGate 生成，随 `state: 'permission_request'` 流事件下发
 * （backend/services/permission_gate.py ApprovalRequest.to_dict()）。
 * 形态与 `GET /api/v1/permissions/pending` 返回的数组元素一致。
 */
export interface PermissionRequest {
  /** 审批请求唯一 ID（UUID），应答时作为路径参数回传 */
  request_id: string;
  /** 触发审批的工具名（如 terminal / file_write） */
  tool_name: string;
  /** 脱敏后的参数摘要（JSON 字符串） */
  args_summary: string;
  /** 风险分级（backend BashRisk / 工具能力推导） */
  risk: 'safe' | 'suspicious' | 'destructive';
  /** 给用户看的审批原因说明 */
  message: string;
  /** 创建时间戳（epoch 秒，浮点） */
  created_at: number;
  /**
   * live-events P1 (2026-09-06): 请求来自编排子代理时携带的任务上下文
   * （后端 SubagentEventSink 注入）。主 agent 审批请求无此字段。
   */
  subagent?: {
    run_id: string;
    task_id: string;
    agent_id: string;
    goal: string;
  };
  /** U15: 写类工具的将写入内容 unified diff（无法生成时缺省，回退 args_summary） */
  diff_preview?: string;
  /**
   * Phase 3.3 (2026-09-17): 工具参数中提取的目标路径（绝对路径），
   * 用于前端"项目级允许"按钮 —— 用户可一键将该路径加入 allowed_paths。
   * 无路径参数时缺省。
   */
  target_path?: string;
}

/** 问题选项 — QuestionDialog 渲染为可选卡片 */
export interface QuestionOption {
  /** 选项文本（回传给 agent 的值） */
  label: string;
  /** 选项的补充说明（可选） */
  description?: string | null;
}

/**
 * 用户提问请求 — M2 part B: AskUserQuestion。
 *
 * 由后端 UserQuestionGate 生成，随 `state: 'ask_user_question'` 流事件下发
 * （backend/services/question_gate.py QuestionRequest.to_dict()）。
 * 形态与 `GET /api/v1/questions/pending` 返回的数组元素一致。
 */
export interface UserQuestion {
  /** 提问请求唯一 ID（UUID），应答时作为路径参数回传 */
  request_id: string;
  /** 展示给用户的完整问题文本 */
  question: string;
  /** 可选短标签（UI chip，如"输出格式"） */
  header?: string | null;
  /** 2-4 个选项 */
  options: QuestionOption[];
  /** 是否允许多选 */
  multi_select: boolean;
  /** 创建时间戳（epoch 秒，浮点） */
  created_at: number;
}

/** 流式聊天工具调用 (对应 OpenAI 工具调用格式) */
export interface AgentToolCall {
  id: string;
  type: 'function';
  function: {
    name: string;
    /** 字符串化的JSON 参数 */
    arguments: string;
  };
}

/** 流式聊天工具结果 */
export interface AgentToolResult {
  tool_call_id: string;
  role: 'tool';
  content: string;
}

// ─── Multi-Agent Orchestration 窄类型事件 (2026-08-11) ─────────────────
// 与 llmStream.ts 双处一致 —— useChat taskBoard 状态机的数据类型。
export interface TaskPlanItem {
  task_id: string;
  agent_id: string;
  goal: string;
  // P1-6 (2026-08-14): 依赖透传 —— 后端 task_plan 事件带 depends_on。
  depends_on?: string[];
  parent_task_id?: string | null;
  depth?: number;
}

export interface TaskPlanEvent {
  state: 'task_plan';
  run_id: string;
  plan: TaskPlanItem[];
}

export type TaskStatusValue = 'queued' | 'running' | 'done' | 'failed' | 'cancelled';

export interface TaskStatusEvent {
  state: 'task_status';
  run_id: string;
  task_id: string;
  status: TaskStatusValue;
  agent_id: string;
  goal: string;
  error: string | null;
  output_preview: string | null;
  // P0-7 (2026-08-20): 重试次数 —— 后端 _emit_task_status 一直携带,此前前端未声明被静默丢弃。
  retry_count?: number;
  // RD13+ (round15): 重派来源任务 ID —— conductor 用 retry_of 重派时携带,
  // 任务树据此渲染"重派"徽章（可追溯哪些任务是重做的）。普通任务无此键。
  retry_of?: string;
  // BU9 (round20) + BU13 (round24): 终态任务附带的本任务 token 消耗 ——
  // round24 起语义收敛为 per-task 归因（usage_events.task_id 过滤），
  // 且预算关闭也携带；queued/running 不带。任务树渲染消耗可见性。
  used_tokens?: number;
  // BU13 (round24): 终态任务执行时长（毫秒）—— started_at→finished_at；
  // 二者齐备才携带。任务树行内渲染耗时徽章。
  duration_ms?: number;
  // BU15 (round29): 【UI 注入，后端不发】running 状态被前端 ingestion
  // 观察到的本地时间戳（Date.now()），任务树行内实时计时用；终态后消失。
  runningSince?: number;
  // live-events P0 (2026-09-06): 派发本批次的 conductor 工具调用 ID —— 聊天流内
  // 把子代理实时步骤关联到 "Delegate <goal>" 卡片的关联键。
  parent_tool_call_id?: string | null;
  // 任务层级（spec 2026-09-19）：后端 _emit_task_status 固定携带，
  // 前端据此渲染任务树缩进/折叠。旧事件缺省 → 根节点、深度 0。
  parent_task_id?: string | null;
  depth?: number;
  // RP1 (round34, 2026-09-19): 被 LLM 动态调整过计划的任务 —— conductor 在 run
  // 中改过目标 / 新增 / 取消该任务时携带，任务树渲染"已调整"徽章（可追溯哪些
  // 任务偏离了初始计划）。普通任务无此键。
  adjusted?: boolean;
}

// ─── live-events P0 (2026-09-06): 子代理实时执行镜像 ───────────────────

/** 子代理单条执行事件的阶段（后端 subagent_events.PHASE_* 镜像） */
export type SubagentEventPhase =
  | 'tool_call'
  | 'tool_result'
  | 'approval_requested'
  | 'approval_resolved'
  | 'question'
  | 'failed';

/** 后端 ``subagent_event`` 镜像事件（与 useChat 宽松 AgentEvent 同步收敛） */
export interface SubagentLiveEvent {
  state: 'subagent_event';
  run_id: string;
  task_id: string;
  agent_id: string;
  goal: string;
  parent_tool_call_id?: string | null;
  phase: SubagentEventPhase;
  iteration?: number;
  /** 任务树行内实时步骤文案（后端预拼装,截断防刷屏） */
  live_step?: string;
  tool_name?: string | null;
  args_summary?: string | null;
  preview?: string | null;
  is_error?: boolean;
  approved?: boolean;
  ts?: number;
}

/** 单个子任务的实时执行态（任务板 ``live[task_id]``,环形缓冲最近 20 条） */
export interface SubagentLiveState {
  /** 行内实时步骤文案(最新一条,如 "🔧 read_file src/x.py") */
  liveStep: string | null;
  /** 等待审批时的工具名(ApprovalDialog 之外,任务行上的 ⏳ 徽章) */
  waitingApproval: string | null;
  /** 最近事件环形缓冲(尾新头旧,后端预算封顶 + 前端 20 条封顶) */
  events: SubagentLiveEvent[];
}

/** 进度可视化 P0-2 (2026-08-12): 整盘概览事件。
 *
 * 后端在 `task_plan` 之后立即推送一次 (total=N, done=0, running=0,
 * queued=N, failed=0),后续也可在 task_status 状态切换时同步更新。
 * 字段是 5 元组,前端 taskBoard.progress 字段与之一一对应。
 */
export interface TaskProgressEvent {
  state: 'task_progress';
  run_id: string;
  total: number;
  done: number;
  running: number;
  queued: number;
  failed: number;
  cancelled: number;
}

/** Wave 2 (2026-08-14): reviewer 复核结论事件（spec §5.2）。
 *
 * 后端 ``_run_review`` 产出 verdict 后推送到 NDJSON 流,前端据此展示
 * "复核通过 / 存在疑问"等结论。字段与 backend ``_emit_task_review`` 一致。
 */
export type ReviewVerdict = 'pass' | 'fail';

export interface TaskReviewEvent {
  state: 'task_review';
  run_id: string;
  task_id: string;
  reviewer_id: string;
  verdict: ReviewVerdict;
  assertion_count: number;
  summary: string;
}

/** P1 todo 接线: agent 自维护清单的全量快照事件,与 llmStream.ts 双处一致。 */
export type TodoStatus = 'pending' | 'in_progress' | 'completed';

export interface TodoItem {
  content: string;
  status: TodoStatus;
  activeForm?: string;
}

export interface TodoSnapshotEvent {
  state: 'todo_snapshot';
  session_id: string;
  todos: TodoItem[];
}

/** 第二轮 C1: 终稿生成统计（毫秒 / tokens；拿不到的项省略） */
export interface GenerationStats {
  input_tokens?: number;
  output_tokens?: number;
  first_token_ms?: number;
  latency_ms?: number;
}

/** 流式聊天事件 (NDJSON 协议的一行) */
export interface AgentEvent {
  state: AgentState;
  iteration: number;
  content?: string;
  reasoning?: string; // LLM 思考/推理过程内容
  tool_call?: AgentToolCall;
  tool_result?: AgentToolResult;
  /** producer 失败信封: LLMError.to_dict() 为 dict; 旧路径/限额拦截为 str */
  error?: string | { type?: string; message?: string; status_code?: number };
  /** client_message_id 协议 (同步 #1155): DONE 附带 assistant 消息的服务端 id */
  message_id?: string;
  /** 首轮对话标记: 标题将在后台生成, 前端稍后补刷侧栏 (同步 #1196) */
  title_pending?: boolean;
  /** 第二轮 B2: DONE 携带的 LLM 终止原因（length = 触达输出上限被截断） */
  finish_reason?: string;
  /** 第二轮 C1: DONE 携带的终稿生成统计（tokens / 首字延迟 / 总耗时） */
  generation_stats?: GenerationStats;
  /** 阶段 4: 当前执行 agent 的 ID (供前端显示"当前处理 agent") */
  agent_id?: string;
  /** M1: state === 'permission_request' 时携带的审批请求详情 */
  permission_request?: PermissionRequest;
  /** M2 part B: state === 'ask_user_question' 时携带的提问详情 */
  user_question?: UserQuestion;
  /** 会话元数据更新事件 (非 agent 事件, 由 producer 在流末尾推送) */
  type?: string;
  subtype?: string;
  title?: string;
  // Round 3 (2026-09-19): state === 'orch_preflight' 时的阶段载荷。
  preflight_phase?: 'clarify' | 'scout';
  // Multi-Agent Orchestration (2026-08-11): 宽松字段（与 llmStream.ts AgentEvent 同步）
  run_id?: string;
  plan?: TaskPlanItem[];
  task_id?: string;
  status?: TaskStatusValue;
  goal?: string;
  output_preview?: string | null;
  retry_count?: number;
  // 进度可视化 P0-2 (2026-08-12): 5 元组快照字段,与 TaskProgressEvent 对齐。
  total?: number;
  done?: number;
  running?: number;
  queued?: number;
  failed?: number;
  cancelled?: number;
  // Wave 2 (2026-08-14): task_review 事件 4 可选字段（仅 state='task_review' 时携带）。
  reviewer_id?: string;
  verdict?: ReviewVerdict;
  assertion_count?: number;
  summary?: string;
  // P1 todo 接线: todo_snapshot 全量快照字段,与 llmStream.ts 双处一致。
  todos?: TodoItem[];
  session_id?: string;
  // Task 10 (2026-09-17): topic_shifted 事件载荷 — 自动切换 segment 时推送。
  segment_id?: number;
  reason?: string;
  // live-events P0 (2026-09-06): subagent_event 镜像字段(收敛类型见
  // SubagentLiveEvent,这里保持宽松 AgentEvent 可直接 cast)。
  phase?: SubagentEventPhase;
  live_step?: string;
  tool_name?: string | null;
  args_summary?: string | null;
  preview?: string | null;
  is_error?: boolean;
  approved?: boolean;
  parent_tool_call_id?: string | null;
  ts?: number;
  // live-events P1: approval_mode 切换回显字段。
  mode?: 'ask' | 'auto';
  // S7 (2026-09-06): artifact_created 事件载荷（工具线程落库后经活跃流推送）。
  artifact?: {
    id: string;
    path: string;
    name: string;
    kind: string;
    size: number;
    created_at: number;
  };
  // R17-E: memory_used 事件载荷（L13 记忆注入命中条目,气泡内可展开）。
  memories?: { id: string; memory_type: string; preview: string }[];
  // R38: skill_activated 事件载荷（A16 自动激活或显式 /skill 调用的技能列表）。
  skills?: { name: string; triggers_matched: string[] }[];
  // R38: compact_triggered 事件载荷（M4 自动压缩统计）。
  compact?: { before: number; after: number; removed: number };
  // TM2 (DSH 对标 R11): context_pressure 事件载荷（确定性上下文计量）。
  context_pressure?: ContextPressurePayload;
  // r71: attachment_rag_used 事件载荷（超长文档检索注入溯源）。
  citations?: {
    media_id: string;
    mode: string;
    chunks?: { index: number; score: number }[];
    filename?: string;
  }[];
  // right-panel R5 (2026-09-19): workspace_changed 事件载荷（写文件工具
  // 落盘后经活跃流推送；path 为工具视角路径，刷新语义以 git status 为准）。
  change?: { path: string; kind?: string };
  // R81: sources_used 事件载荷（检索类工具命中，done 前一次性推送）。
  sources?: MessageSource[];
}

// ==================== 错误类型定义 ====================

export interface ApiError {
  error: string;
  message: string;
  details?: Record<string, unknown>;
  llmError?: LLMErrorResponse;
}

// ==================== Chat 配置 ====================

export interface ChatConfig {
  apiKey?: string;
  apiUrl?: string;
  model?: string;
  maxContext?: number;
  /** Task 5 (2026-09-15): auto-context resolution flag.
   * true = backend resolves effective window from catalog; false = use maxContext as fixed cap.
   */
  autoContext?: boolean;
  temperature?: number;
  // 推理参数（PR-7a 透传到后端 → LLMConfig → 请求体）
  // - provider: 前端在 settings 选的真实 provider,后端用它路由
  //   (openai / claude / gemini / deepseek / ollama / custom)
  // - reasoningEffort: OpenAI o1/o3/5 + DeepSeek OpenAI 兼容代理
  // - thinkingBudget: Gemini 2.5 OpenAI 兼容模式
  provider?: string;
  reasoningEffort?: 'low' | 'medium' | 'high';
  thinkingBudget?: number;
  /** Multi-Agent Orchestration: auto | force_multi | force_single | template:<id>（缺省 auto） */
  orchestrationMode?: string;
  // Wave 3 (2026-08-14): resume 恢复流 —— plan_override 逐字恢复（跳过 LLM 拆解）。
  planOverride?: TaskPlanItem[];
  runId?: string;
  // PM1 (round8): 单 agent 计划模式 —— 本次 run 只读 + 计划产出指令，
  // 完成后前端出批准条（与 orchestrationMode 互斥，后端强制 single）。
  planMode?: boolean;
  // 对标 S2 (2026-09-13): 临时聊天 —— 本轮不注入记忆也不做记忆提取。
  memoryDisabled?: boolean;
  /**
   * Task 5 (2026-09-17): 上下文重置标记 —— true 时后端在本轮消息前插入
   * topic_separator 并清空 LLM 历史窗口，实现"新话题"显式分界。
   */
  contextReset?: boolean;
  /** 第二轮 C2: 原位重新生成 —— 锚点 user 消息 id（后端不再落 user 消息） */
  regenerateOf?: string;
}
