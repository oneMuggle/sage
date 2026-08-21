/**
 * Sage API - 类型定义
 */

import type { LLMErrorResponse } from '../lib/errorMapping';

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

export type WorkspaceSearchKind = 'file' | 'office-ppt' | 'office-word' | 'office-excel';

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
  docType: OfficeDocType;
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
  tool_calls?: ToolCall[];
  tool_call_id?: string;
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
  | 'acting'
  | 'permission_request' // M1: 工具审批卡点 — 等待用户批准/拒绝
  | 'ask_user_question' // M2 part B: AskUserQuestion 卡点 — 等待用户选择/填写
  | 'observing'
  | 'content_delta'
  | 'done'
  | 'failed'
  // Multi-Agent Orchestration (2026-08-11)
  | 'task_plan'
  | 'task_status'
  // 进度可视化 P0-2 (2026-08-12): 整盘概览事件,在 task_plan 之后立刻
  // 推送一次,前端 taskBoard 渲染"已拆解为 N 个子任务"头部信息时不必
  // 等待 subtask 状态切换就能拿到 total。后续 5 元组也可由前端 reducer
  // 实时从 task_status 聚合,本事件只承担初始化职责。
  | 'task_progress'
  // Wave 2 (2026-08-14): reviewer 复核结论事件,见 TaskReviewEvent。
  | 'task_review';

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

/** 流式聊天事件 (NDJSON 协议的一行) */
export interface AgentEvent {
  state: AgentState;
  iteration: number;
  content?: string;
  reasoning?: string; // LLM 思考/推理过程内容
  tool_call?: AgentToolCall;
  tool_result?: AgentToolResult;
  error?: string;
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
  // Wave 2 (2026-08-14): task_review 事件 4 可选字段（仅 state='task_review' 时携带）。
  reviewer_id?: string;
  verdict?: ReviewVerdict;
  assertion_count?: number;
  summary?: string;
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
}

// ==================== Memory 类型定义 ====================

export interface Memory {
  id: string;
  content: string;
  summary?: string;
  memory_type?: 'episodic' | 'semantic' | 'working';
  session_id?: string;
  importance: number;
  tags: string[];
  created_at: number;
  accessed_at?: number;
  access_count: number;
}

// ==================== Knowledge 类型定义 ====================

export interface KnowledgeDoc {
  id: string;
  title: string;
  description: string;
  pages: number;
  updated_at: string;
  category: string;
  tags?: string[];
}

// ==================== Skills 类型定义 (PR-7) ====================

/**
 * SKILL.md v2 DispatchMode 元数据 (M9) — 嵌套对象, 与后端
 * backend/skills/skill_md/skill.py::DispatchMode 字段一一对应。
 *
 * - disable_model_invocation: true → chat 层阻止自动触发
 * - user_invocable: true → 用户可通过 slash command 主动调用
 * - user_invocable_name: slash command 名 (如 "/review");为 null 时回退到 name
 * - command_dispatch: 'auto' (默认, LLM 决定) / 'tool' (强制工具调用) / 'prompt' (注入 prompt)
 *
 * builtin 技能没有 dispatch key (后端 list_skills_extended 对 builtin 省略)。
 */
export interface SkillDispatch {
  disable_model_invocation: boolean;
  user_invocable: boolean;
  user_invocable_name: string | null;
  command_dispatch: 'auto' | 'tool' | 'prompt';
}

export interface Skill {
  name: string;
  description: string;
  triggers: string[];
  parameters: Record<string, unknown>;
  examples: string[];
  enabled: boolean;
  usage_count: number;
  // SKILL.md 适配层 (PR-8) 新增字段 — builtin 时不存在
  source?: 'builtin' | 'skillmd';
  body?: string;
  scripts?: string[];
  base_dir?: string;
  version?: string;
  // agentskills.io spec optional fields (PR-84): builtin 永远 None,SKILL.md 才填充。
  // 后端 list_skills_extended 序列化,tuple → list(JSON-friendly)。
  license?: string | null;
  compatibility?: string | null;
  allowed_tools?: string[];
  // SKILL.md v2 DispatchMode (M9) — builtin 时不存在
  dispatch?: SkillDispatch;
  // 生命周期态（curator）— active=近期在用 / stale=冷（含从未用）/ archived=用户归档
  lifecycle?: 'active' | 'stale' | 'archived';
}

export interface SkillExecuteRequest {
  action?: string;
  args?: Record<string, unknown>;
}

export interface SkillExecuteResult {
  success: boolean;
  content?: unknown;
  metadata: Record<string, unknown>;
  error?: string;
}

/**
 * Skill delete result. Returned by `skillsApi.delete(name)`.
 *
 * - `deleted`: 永远是 `true`（失败路径通过 throw error 表达）
 * - `name`: 已删除的 skill 名字
 * - `base_dir`: 已删除的磁盘路径 (调试/审计用)
 */
export interface DeleteSkillResult {
  deleted: boolean;
  name: string;
  base_dir?: string;
}

/**
 * Skill draft produced by the Background Review pipeline.
 *
 * Mirrors the backend `SkillDraft` dataclass / `_draft_to_dict` shape
 * (see `backend/api/legacy_routes.py`). Drafts live in a SQLite table
 * and are surfaced to the user for approval/rejection via the
 * "Pending Drafts" tab on the Skills page.
 */
export interface SkillDraft {
  id: string;
  name: string;
  description: string;
  when_to_use: string;
  content: string;
  trigger_type: string;
  source_session_id: string;
  source_context: Record<string, unknown>;
  status: 'pending' | 'approved' | 'rejected';
  created_at: number;
}

/** Response shape of GET /skill-drafts. */
export interface SkillDraftListResponse {
  drafts: SkillDraft[];
}

/** Response shape of POST /skill-drafts/{id}/approve. */
export interface SkillDraftApproveResponse {
  status: 'approved';
  skill_name: string;
  draft_id: string;
}

/** Response shape of POST /skill-drafts/{id}/reject. */
export interface SkillDraftRejectResponse {
  status: 'rejected';
  draft_id: string;
}

/**
 * Response shape of POST /learn (Background Review explicit trigger).
 *
 * Backend enqueues a review event with trigger_type="explicit_learn".
 * The Background Review worker picks it up and produces skill draft(s)
 * that appear in the Skills page "Pending Drafts" tab.
 */
export interface LearnResponse {
  status: 'queued';
  message: string;
}

// ==================== Agents 类型定义 ====================

export interface AgentProfile {
  id: string;
  name: string;
  role: string;
  description: string;
  system_prompt: string;
  tools: string[];
  memory_access: string[];
  model_config: {
    model: string;
    temperature: number;
    max_tokens: number;
  };
  max_iterations: number;
  enabled: boolean;
  /** 后端 PR-3 起返回; PR-4 PATCH 后被刷新 */
  updated_at?: number;
}

/**
 * PR-4 `update_agent` 命令的部分更新 payload。
 *
 * 字段全为可选 — 仅传需要修改的字段, 缺省字段保留原值 (PATCH 语义)。
 * 形状匹配 Tauri `AgentUpdateRequest` (src-tauri/src/models.rs:134),
 * 后端再映射到 Pydantic `AgentUpdate` 做白名单/范围校验。
 *
 * 注: 仅暴露 9 个允许字段，不含 `id` (id 不可变, 见 agent_repo.py 注释)
 * 与 `updated_at` (DB 自动维护)。
 */
export interface AgentUpdate {
  name?: string;
  role?: string;
  system_prompt?: string;
  tools?: string[];
  memory_access?: string[];
  model_config?: AgentProfile['model_config'];
  max_iterations?: number;
  enabled?: boolean;
  description?: string;
}

/** POST /agents 请求体（US-4 角色可扩展）。 */
export interface AgentCreate {
  id: string;
  name: string;
  role?: string;
  system_prompt?: string;
  tools?: string[];
  memory_access?: string[];
  modelConfigData?: Record<string, unknown>;
  maxIterations?: number;
  enabled?: boolean;
  description?: string;
}

// ─── Scheduled Tasks (Phase 8) ───────────────────────────────

export type ScheduleKind = 'once' | 'recurring';

export type Schedule = { kind: 'once'; at: number } | { kind: 'recurring'; cron: string };

export interface ScheduledTask {
  id: string;
  name: string;
  type: ScheduleKind;
  schedule: Schedule;
  session_id: string;
  content: string;
  enabled: boolean;
  last_run?: number | null;
  next_run?: number | null;
  created_at: number;
}

export interface CreateTaskInput {
  name: string;
  type: ScheduleKind;
  schedule: Schedule;
  session_id: string;
  content: string;
}

export interface UpdateTaskInput {
  name?: string;
  enabled?: boolean;
}

// ============================================================================
// Multi-agent orchestration types (Phase 4)
// ============================================================================

export type LaneStatus =
  | 'created'
  | 'ready'
  | 'running'
  | 'blocked'
  | 'succeeded'
  | 'failed'
  | 'stopped'
  | 'cancelled';

export type HeartbeatStatus = 'healthy' | 'stalled' | 'transport_dead';

export type TaskStatus = 'created' | 'running' | 'blocked' | 'completed' | 'failed' | 'stopped';

export type TeamStatus = 'created' | 'running' | 'completed' | 'failed' | 'cancelled';

export type LaneEventType =
  | 'lane.started'
  | 'lane.ready'
  | 'lane.running'
  | 'lane.blocked'
  | 'lane.succeeded'
  | 'lane.failed'
  | 'lane.stopped'
  | 'lane.commit.created'
  | 'lane.pr.opened'
  | 'lane.merged';

export type EventProvenance = 'LiveLane' | 'Recovery' | 'Retry' | 'Heartbeat' | 'Manual';

export interface LaneHeartbeat {
  last_ping_at: number;
  transport_alive: boolean;
  status: HeartbeatStatus;
}

export interface Lane {
  lane_id: string;
  task_id: string;
  agent_id: string | null;
  status: LaneStatus;
  created_at: number;
  started_at: number | null;
  completed_at: number | null;
  worktree: string | null;
  heartbeat: LaneHeartbeat | null;
  error: string | null;
  permission_preset: string;
  metadata: Record<string, unknown>;
}

export interface Task {
  task_id: string;
  name: string;
  description: string;
  task_type: string;
  status: TaskStatus;
  priority: number;
  team_id: string | null;
  created_at: number;
  started_at: number | null;
  completed_at: number | null;
}

export interface Team {
  team_id: string;
  name: string;
  task_ids: string[];
  status: TeamStatus;
  created_at: number;
  updated_at: number;
  metadata: Record<string, unknown>;
}

export interface LaneEvent {
  event_id: string;
  event_type: LaneEventType;
  lane_id: string;
  task_id: string;
  agent_id: string | null;
  timestamp: number;
  provenance: EventProvenance;
  metadata: Record<string, unknown>;
}

export interface LaneBoardGroup {
  active: Lane[];
  blocked: Lane[];
  finished: Lane[];
}

/** Task summary returned by POST /orchestration/lanes (M5). */
export interface PlannerTaskOut {
  task_id: string;
  name: string;
  description: string;
  task_type: string;
  status: TaskStatus;
  blocked_by: string[];
  team_id: string | null;
  agent_hint: string | null;
}

/** Response of POST /orchestration/lanes (M5 planner decomposition). */
export interface CreateLanesResponse {
  ok: boolean;
  team_id: string;
  lanes: Lane[];
  tasks: PlannerTaskOut[];
}

// ──────────────────────────────────────────────────────────────────────
// Office document types (Phase 1, plan §3.4)
// Backend counterpart: backend/office/models.py
// ──────────────────────────────────────────────────────────────────────

export type OfficeDocType = 'ppt' | 'word' | 'excel';

export type OfficeDocStatus = 'parsed' | 'generated' | 'edited';

export interface OfficeDocumentMetadata {
  page_count?: number;
  sheet_count?: number;
  paragraph_count?: number;
  table_count?: number;
  file_size_bytes: number;
}

export interface OfficeDocumentSummary {
  id: string;
  workspace_path: string;
  doc_type: OfficeDocType;
  original_filename: string | null;
  generated_filename: string;
  status: OfficeDocStatus;
  created_at: number;
  updated_at: number;
  metadata: OfficeDocumentMetadata;
}

export interface OfficePptSlideContent {
  index: number;
  title: string | null;
  text_blocks: string[];
  table_count: number;
  image_count: number;
  notes: string | null;
}

export interface OfficePptReadResult {
  summary: OfficeDocumentSummary;
  slides: OfficePptSlideContent[];
}

export interface OfficeWordParagraphContent {
  style: string;
  text: string;
  level: number;
}

export interface OfficeWordTableContent {
  rows: string[][];
}

export interface OfficeWordReadResult {
  summary: OfficeDocumentSummary;
  paragraphs: OfficeWordParagraphContent[];
  tables: OfficeWordTableContent[];
  images: number;
}

export interface OfficeExcelSheetContent {
  name: string;
  rows: string[][];
  max_row: number;
  max_col: number;
}

export interface OfficeExcelReadResult {
  summary: OfficeDocumentSummary;
  sheets: OfficeExcelSheetContent[];
}

export interface OfficeReadRequest {
  workspace_path: string;
  file_path: string;
  max_size_bytes?: number;
}

// ──────────────────────────────────────────────────────────────────────
// Generate request types (Phase 1.4, plan §4.1.4)
// Backend counterpart: OfficePptGenerateRequest / OfficeWordGenerateRequest /
// OfficeExcelGenerateRequest in backend/office/models.py
// ──────────────────────────────────────────────────────────────────────

export interface PptSlideSpec {
  title: string;
  bullets?: string[];
  notes?: string;
}

export interface OfficePptGenerateRequest {
  workspace_path: string;
  filename: string;
  slides: PptSlideSpec[];
  template?: 'default' | 'minimal';
}

export interface WordParagraphSpec {
  heading?: 'h1' | 'h2' | 'h3';
  text: string;
}

export interface WordTableSpec {
  headers: string[];
  rows: string[][];
}

export interface OfficeWordGenerateRequest {
  workspace_path: string;
  filename: string;
  title: string;
  paragraphs?: WordParagraphSpec[];
  tables?: WordTableSpec[];
}

export interface ExcelSheetSpec {
  name: string;
  headers?: string[];
  rows?: string[][];
}

export interface OfficeExcelGenerateRequest {
  workspace_path: string;
  filename: string;
  sheets: ExcelSheetSpec[];
}

export interface OfficeDocumentListResponse {
  documents: OfficeDocumentSummary[];
  total: number;
}

export interface OfficeDeleteResponse {
  id: string;
  deleted: boolean;
}
