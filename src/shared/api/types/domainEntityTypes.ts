// ==================== Memory 类型定义 ====================

/** 对标 S2: 一次记忆写入（台账条目），用于聊天内联"记住了"提示 */
export interface MemoryWriteRecord {
  seq: number;
  id: string;
  kind: 'memory' | 'profile';
  content: string;
  category: string;
  memory_type: string;
  session_id: string;
  created_at: number;
}

export interface MemoryWritesResponse {
  items: MemoryWriteRecord[];
  latest_seq: number;
}

/** 对标 S2: 用户画像条目（"关于我"卡片） */
export interface UserProfileEntry {
  id: string;
  content: string;
  category: string;
  importance: number;
  source: string;
  created_at: number;
  updated_at: number;
}

export interface UserProfileResponse {
  items: UserProfileEntry[];
  categories: string[];
  snapshot: string;
  char_limit: number;
}

/** P2 项目画像条目（项目级 MEMORY.md，按 project_key 分组） */
export interface ProjectProfileEntry extends UserProfileEntry {
  project_key: string;
}

export interface ProjectProfileResponse {
  project_key: string;
  items: ProjectProfileEntry[];
  categories: string[];
  snapshot: string;
  char_limit: number;
  projects: string[];
}

/**
 * 单条记忆记录。Task 2 起 ``layer`` / ``source`` 由后端 ``/memory/list`` 直接
 * 注入:
 * - ``layer`` 表示该条记录归属的层 (``'episodic'`` / ``'semantic'`` /
 *   ``'working'`` / ``'session_summary'``)
 * - ``source`` 表示层来源(同 ``layer``);与 DB 列 ``source``('auto'/'manual')
 *   语义不同
 *
 * 批次三 step 6 (spec §4.3 line 150) 起:
 * - ``source`` 新增 ``'working'`` 和 ``'session_summary'``,对应工作记忆与会话
 *   摘要的展示徽章。
 * - ``status`` 仅 ``session_summary`` 行有值,取 ``'pending'`` / ``'ready'`` /
 *   ``'failed'``;失败行带 ``error_message`` 供诊断展示。
 */
export interface Memory {
  id: string;
  content: string;
  summary?: string;
  memory_type?: 'episodic' | 'semantic' | 'working' | 'session_summary';
  /** 该条记录归属的记忆层。Task 2 新增;step 6 扩展到 session_summary。 */
  layer?: 'episodic' | 'semantic' | 'working' | 'session_summary';
  /** 该条记录的层来源(episodic/semantic/working/session_summary)。 */
  source?: 'episodic' | 'semantic' | 'working' | 'session_summary';
  session_id?: string;
  /** session_summary 专用:对应的源 turn id(可选)。 */
  source_turn_id?: string;
  /** session_summary 专用:行状态。 */
  status?: 'pending' | 'ready' | 'failed';
  /** session_summary 专用:失败时携带的诊断。 */
  error_message?: string;
  importance: number;
  tags: string[];
  created_at: number;
  /** 毫秒时间戳副本,UI 可优先用此避免二次乘法。Task 2 新增。 */
  created_at_ms?: number;
  accessed_at?: number;
  access_count: number;
  /** P1 作用域轴 (2026-09-18): user=跨项目可见 / project=归属某项目 / global=全局共享。 */
  scope?: 'user' | 'project' | 'global';
  /** scope='project' 时的项目目录 (规范化绝对路径)。 */
  project_key?: string;
}

/**
 * ``/memory/list`` 返回的 envelope,Task 2 起替换裸 list 契约。
 * 旧 caller 拿 ``resp.json()`` 直接当数组用 — 现在必须读 ``.items``。
 *
 * 批次三 step 6 起:
 * - ``layer`` 扩展为 ``'working'`` / ``'session_summary'`` / ``'all'``(四层)
 * - ``source_breakdown`` 新增 ``working`` / ``session_summary`` 计数
 * - ``offset`` 字段回显后端的 offset cursor
 */
export interface MemoryListResponse {
  items: Memory[];
  total: number;
  page: number;
  page_size: number;
  /** 后端 offset cursor 回显(step 6 新增)。 */
  offset?: number;
  /** 请求归一化后的查询层;step 6 扩展到 working/session_summary。 */
  layer: 'episodic' | 'semantic' | 'working' | 'session_summary' | 'all';
  source_breakdown: {
    working: number;
    session_summary: number;
    episodic: number;
    semantic: number;
  };
}

/**
 * ``/memory/summaries`` 返回的 envelope(批次三 step 6 新增)。
 * ``session_id`` 必填,不允许"全部 session 的摘要"视图(spec step 5 严禁
 * 跨 session 串味)。
 */
export interface MemorySummariesListResponse {
  session_id: string;
  items: Memory[];
  total: number;
  page: number;
  page_size: number;
  offset?: number;
}

/** R17-B: 记忆固化（evolution/memory_consolidation）任务统计 */
export interface MemoryConsolidationResult {
  /** 晋升为语义记忆的条数 */
  promoted: number;
  /** 衰减 importance 的条数 */
  decayed: number;
  total: number;
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
  // Round 17 管理面：钉住态（pin 后不可归档、巡检不给出 archive 建议）。
  // 旧后端列表不透出该字段 — optional 向后兼容。
  pinned?: boolean;
}

/** 巡检建议条目 — GET /skills/consolidation/suggestions（Round 17 管理面）。 */
export interface ConsolidationSuggestion {
  skill_names: string[];
  suggestion: Record<string, unknown>;
  created_at: number;
}

/** 固化巡检结果 — POST /skills/consolidation/scan。 */
export interface ConsolidationScanResult {
  suggestions: ConsolidationSuggestion[];
  scanned: number;
  drafts_created: number;
}

/** 巡检建议采纳结果 — POST /skills/consolidation/accept。 */
export interface ConsolidationAcceptResult {
  archived: string[];
  skipped_pinned: string[];
  missing: string[];
}

/**
 * P2-2 技能审计台账条目 — GET /skills/{name}/audit。
 *
 * 注意一个真实的后端限制：list 接口的 SQL **不返回** before_content /
 * after_content（backend/skills/audit.py 的 SELECT 只取这 6 列），所以前端
 * 拿不到 diff，只能做元数据时间线。不要在 UI 里承诺展示「改了什么内容」——
 * 那是后端还没给的数据。
 */
export interface SkillAuditEntry {
  id: number;
  skill_name: string;
  action: 'create' | 'update' | 'archive' | 'restore' | 'rollback' | 'consolidation_note';
  actor: 'user' | 'system';
  source: string | null;
  /** 毫秒时间戳 */
  created_at: number;
}

/** GET /skills/{name}/audit 的响应。 */
export interface SkillAuditResponse {
  skill_name: string;
  entries: SkillAuditEntry[];
}

/**
 * P2-2 技能回滚结果 — POST /skills/{name}/rollback。
 *
 * 语义是**回到上一个有快照的版本**（后端取 latest_before_snapshot），没有条目
 * 粒度参数：UI 只能提供「回滚到上一版」，不能做「点某条历史回到那一版」。
 */
export interface SkillRollbackResult {
  status: 'rolled_back';
  skill_name: string;
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
  last_attempt?: number | null;
  last_status?: 'never' | 'succeeded' | 'failed';
  last_error?: string | null;
  run_count?: number;
  max_runs?: number | null;
  created_at: number;
}

export interface CreateTaskInput {
  name: string;
  type: ScheduleKind;
  schedule: Schedule;
  session_id: string;
  content: string;
  enabled?: boolean;
  max_runs?: number | null;
}

export interface UpdateTaskInput {
  name?: string;
  enabled?: boolean;
  type?: ScheduleKind;
  schedule?: Schedule;
  session_id?: string;
  content?: string;
  max_runs?: number | null;
}

// Multi-agent orchestration types (Phase 4)
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
  | 'lane.merged'
  | 'lane.acceptance.completed'
  | 'lane.accepted'
  | 'lane.rejected';

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

// ============================================================================
// LaneBoard snapshot (P2-5: GET /orchestration/board)
// 形态对齐 backend/orchestration/lane_board.py 的 to_dict()
// ============================================================================

/** Per-lane freshness derived from heartbeat age (lane_board.LaneFreshness). */
export interface LaneFreshnessInfo {
  lane_id: string;
  last_heartbeat_at: number | null;
  age_ms: number | null;
  level: 'fresh' | 'stale' | 'dead';
  reasons: string[];
}

/** Aggregate freshness counts + worst-of-three overall level. */
export interface FreshnessSummaryInfo {
  total: number;
  fresh: number;
  stale: number;
  dead: number;
  overall_level: 'fresh' | 'stale' | 'dead';
}

/** One lane rendered on the board (lane_board.BoardEntry). */
export interface LaneBoardEntry {
  lane_id: string;
  task_id: string;
  agent_id?: string | null;
  status: string;
  freshness?: LaneFreshnessInfo;
  heartbeat_status?: string | null;
  last_event_at?: number;
  last_event_type?: string;
}

/**
 * Snapshot of all lanes grouped by status with freshness.
 * `view` / `redaction_provenance` only appear on projection responses
 * (`?view=ui_minimal`); plain ops_full omits them.
 */
export interface LaneBoardSnapshot {
  schema_version: string;
  generated_at: number;
  generated_by: string;
  active: LaneBoardEntry[];
  blocked: LaneBoardEntry[];
  finished: LaneBoardEntry[];
  freshness_summary: FreshnessSummaryInfo;
  /** projection 响应独有（ops_full 无此字段） */
  view?: string;
  redaction_provenance?: Record<string, string>;
}

/**
 * ui_minimal 投影响应信封（GET /orchestration/board?view=ui_minimal）。
 *
 * 形态对齐 backend/orchestration/lane_board.py `BoardProjection.to_dict()`：
 * 与 ops_full 快照（LaneBoardSnapshot）是两种不同信封 —— ui_minimal 不含
 * active/blocked/finished 分组，只有投影后的扁平 entries（lifecycle 字段族）
 * + 协商元数据（父快照 hash / schema 版本 / 降级 / 删减溯源）。
 */
export interface BoardProjectionEnvelope {
  parent_content_hash: string;
  parent_schema_version: string;
  view: string;
  entries: Array<Record<string, unknown>>;
  downgrade_for_compatibility: string[];
  redaction_provenance: Record<string, string>;
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

/**
 * Document kind discriminator. `pdf` added in Office parity batch 1
 * (item 1.2) — backend counterpart `OfficeDocType` already carries
 * `PDF = "pdf"` (backend/office/models.py:38-44).
 */
