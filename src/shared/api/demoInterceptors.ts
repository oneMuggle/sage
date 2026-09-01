/**
 * 演示模式拦截器 (2026-08-27):
 *
 * 把 src/demo 路由里的 mock 数据下沉到 API client 层。演示模式开关打开时,
 * 各 api client (memoryApi / skillsApi / knowledgeApi / orchestrationClient)
 * 顶部调用 isDemoMode() 命中即返回内置 demo 数据, 真实页面无需修改.
 *
 * 设计要点:
 * - isDemoMode() 直接读 zustand store (.getState()), 不走 React hook —
 *   api client 不在 React 渲染路径, 不能用 useSettings().
 * - demo 数据是真实 schema 形状的 Memory[] / Skill[] / KnowledgeDoc[] /
 *   Lane[] / LaneBoardSnapshot, 不是 demo-only 的 wrapper, 所以真实组件
 *   渲染出来的就是真实 UI 形态, 看不出是 mock.
 * - 写操作 (skillsApi.toggle/archive, orchestrationClient.createLane/
 *   cancelLane) 不挡, 仍走真实 invoke 路径 — 演示模式不假装能落库.
 */

import { useSettingsStore } from '../../features/manage-settings/settingsStore';

import { getDemoModeOverride } from './demoRuntime';
import type { McpServerConfig, McpStatusReport } from './mcpClient';
import type {
  AgentProfile,
  CreateLanesResponse,
  DeleteSkillResult,
  KnowledgeDoc,
  Lane,
  LaneBoardSnapshot,
  LaneEvent,
  LearnResponse,
  Memory,
  Message,
  OfficeDeleteResponse,
  OfficeDocumentSummary,
  OfficeExcelReadResult,
  OfficePptReadResult,
  OfficeWordReadResult,
  ScheduledTask,
  Session,
  SessionCompactResult,
  SessionExportResult,
  Skill,
  SkillExecuteResult,
} from './types';
import type { UsageSummary } from './usageApi';

/**
 * 顶层开关判定: 渲染期间 (含 async 回调) 都会拿到最新 settings.
 *
 * 2026-08-27 修复: 优先读 main 进程经 webPreferences.additionalArguments →
 * preload argv 同步注入的标志。首屏请求 (loadSessions / loadMessages 等)
 * 早于 loadSettings 完成, 只读 store 会竞态漏拦截 → 请求打到已跳过的后端
 * 报 ECONNREFUSED。store 兜底保留, 覆盖设置页即时切换的场景。
 */
export function isDemoMode(): boolean {
  const override = getDemoModeOverride();
  if (override !== undefined) return override;
  if (typeof window !== 'undefined' && window.electronAPI?.demoMode === true) return true;
  return useSettingsStore.getState().settings.demoMode === true;
}

// =========================================================================
// Memory demo 数据 (6 条覆盖 4 层)
// =========================================================================

const NOW = Date.now();

export const DEMO_MEMORIES: Memory[] = [
  {
    id: 'mem-001',
    content: '用户偏好使用流式输出, 不喜欢等待完整回复生成。',
    summary: '流式输出偏好',
    memory_type: 'semantic',
    layer: 'semantic',
    source: 'semantic',
    importance: 8,
    tags: ['偏好', '对话'],
    created_at: NOW - 1000 * 60 * 60 * 24 * 7,
    created_at_ms: NOW - 1000 * 60 * 60 * 24 * 7,
    accessed_at: NOW - 1000 * 60 * 60 * 2,
    access_count: 12,
  },
  {
    id: 'mem-002',
    content:
      '用户上月调研 RAG 检索增强生成文献时, 偏好"方法-数据集-结论"三栏格式整理文献, 要求参考文献中近三年来源不少于 5 篇。',
    summary: '文献整理偏好',
    memory_type: 'episodic',
    layer: 'episodic',
    source: 'episodic',
    importance: 7,
    tags: ['调研', '偏好'],
    created_at: NOW - 1000 * 60 * 60 * 24 * 14,
    created_at_ms: NOW - 1000 * 60 * 60 * 24 * 14,
    accessed_at: NOW - 1000 * 60 * 60 * 24,
    access_count: 5,
  },
  {
    id: 'mem-003',
    content: '用户曾在 2026-08-12 要求用 markdown 表格输出, 而不是 JSON。',
    memory_type: 'working',
    layer: 'working',
    source: 'working',
    importance: 4,
    tags: ['格式', '偏好'],
    created_at: NOW - 1000 * 60 * 60 * 24 * 3,
    created_at_ms: NOW - 1000 * 60 * 60 * 24 * 3,
    accessed_at: NOW - 1000 * 60 * 30,
    access_count: 2,
  },
  {
    id: 'mem-004',
    content:
      '本周多智能体协作联调要点: 1) Planner 拆分粒度 ≤ 4 子任务; 2) Reviewer 必须监听 Executor 进度; 3) 心跳超时 30s.',
    summary: '协作模式经验',
    memory_type: 'semantic',
    layer: 'semantic',
    source: 'semantic',
    importance: 9,
    tags: ['协作', '经验'],
    created_at: NOW - 1000 * 60 * 60 * 24 * 2,
    created_at_ms: NOW - 1000 * 60 * 60 * 24 * 2,
    accessed_at: NOW - 1000 * 60 * 5,
    access_count: 8,
  },
  {
    id: 'mem-005',
    content:
      'Session 总结: 与用户讨论了 Sage 后端的 asyncio 事件循环阻塞问题, 计划用 threading.Lock + async handler 隔离 DB 调用.',
    summary: '事件循环修复讨论',
    memory_type: 'session_summary',
    layer: 'session_summary',
    source: 'session_summary',
    session_id: 'sess-demo-001',
    status: 'ready',
    importance: 6,
    tags: ['session-summary', '后端'],
    created_at: NOW - 1000 * 60 * 60 * 24,
    created_at_ms: NOW - 1000 * 60 * 60 * 24,
    accessed_at: NOW - 1000 * 60 * 60,
    access_count: 1,
  },
  {
    id: 'mem-006',
    content:
      'Office 集成 M0 阶段完成: pickAndImportOfficeFile 走 IPC bridge, 7 个通道接 Chat-native CRUD。',
    memory_type: 'semantic',
    layer: 'semantic',
    source: 'semantic',
    importance: 7,
    tags: ['office', '集成'],
    created_at: NOW - 1000 * 60 * 60 * 12,
    created_at_ms: NOW - 1000 * 60 * 60 * 12,
    accessed_at: NOW - 1000 * 60 * 60 * 6,
    access_count: 3,
  },
];

// =========================================================================
// Knowledge demo 数据 (8 个文档覆盖多 category)
// =========================================================================

export const DEMO_KNOWLEDGE_DOCS: KnowledgeDoc[] = [
  {
    id: 'kb-001',
    title: 'Sage 后端 FastAPI 路由总览',
    description: '所有 /api/v1/* 端点的设计契约、错误码约定与典型调用示例。',
    pages: 24,
    updated_at: '2026-08-22',
    category: 'backend',
    tags: ['fastapi', 'api'],
  },
  {
    id: 'kb-002',
    title: '多智能体编排协议规范 v2.3',
    description: 'Lane/Task 状态机、事件类型、规划器输出 schema 与回滚策略。',
    pages: 38,
    updated_at: '2026-08-20',
    category: 'orchestration',
    tags: ['lane', 'agent'],
  },
  {
    id: 'kb-003',
    title: 'Skills SKILL.md 适配层设计',
    description: 'PR-8 引入的 builtin ↔ SKILL.md 双形态, 字段映射与归档机制。',
    pages: 16,
    updated_at: '2026-08-18',
    category: 'skills',
    tags: ['skill-md'],
  },
  {
    id: 'kb-004',
    title: 'Electron 主进程 IPC 桥接规范',
    description: 'sage:invoke / sage:listen / sage:dialog:* 通道命名、payload 契约与错误传播。',
    pages: 22,
    updated_at: '2026-08-15',
    category: 'electron',
    tags: ['ipc', 'preload'],
  },
  {
    id: 'kb-005',
    title: 'LLM Provider 端点协议适配',
    description:
      'OpenAI-compatible / Anthropic / Gemini / Ollama 四协议的 request/response 转换规则。',
    pages: 31,
    updated_at: '2026-08-23',
    category: 'llm',
    tags: ['provider', 'protocol'],
  },
  {
    id: 'kb-006',
    title: '记忆系统四层架构',
    description: 'episodic / semantic / working / session_summary 的写入路径、检索索引与淘汰策略。',
    pages: 19,
    updated_at: '2026-08-10',
    category: 'memory',
    tags: ['episodic', 'semantic'],
  },
  {
    id: 'kb-007',
    title: 'Office 文档 CRUD 实现细节',
    description: 'pickAndImport → 原子 staging → complete/discard 生命周期, 错误码表。',
    pages: 27,
    updated_at: '2026-08-19',
    category: 'office',
    tags: ['staging', 'token'],
  },
  {
    id: 'kb-008',
    title: 'Release 阶段晋升流程 (alpha → beta → rc → stable)',
    description: 'GitFlow + 显式 release 阶段, cherry-pick 回灌策略, tag 命名约定。',
    pages: 12,
    updated_at: '2026-08-25',
    category: 'release',
    tags: ['gitflow', 'release'],
  },
];

// =========================================================================
// Skills demo 数据 (5 个 builtin + 3 个 SKILL.md)
// =========================================================================

export const DEMO_SKILLS: Skill[] = [
  {
    name: 'bash',
    description: '执行 shell 命令, 返回 stdout/stderr/exit code。',
    triggers: ['运行命令', 'shell', 'exec'],
    parameters: { command: 'string', timeout: 'number?' },
    examples: ['bash: ls -la', 'bash: pwd'],
    enabled: true,
    usage_count: 142,
    source: 'builtin',
  },
  {
    name: 'read_file',
    description: '读取本地文件内容, 支持行范围与编码。',
    triggers: ['查看文件', 'cat', '读取'],
    parameters: { path: 'string', offset: 'number?', limit: 'number?' },
    examples: ['read_file: src/main.ts'],
    enabled: true,
    usage_count: 87,
    source: 'builtin',
  },
  {
    name: 'edit_file',
    description: '字符串精确替换写回文件, 必须先 read_file。',
    triggers: ['修改文件', 'edit', '替换'],
    parameters: { path: 'string', old: 'string', new: 'string' },
    examples: ['edit_file: foo.ts old=bar new=baz'],
    enabled: true,
    usage_count: 53,
    source: 'builtin',
  },
  {
    name: 'web_search',
    description: 'Exa 网络搜索, 返回 top-N 结果 + 高亮。',
    triggers: ['搜索', '联网', '查一下'],
    parameters: { query: 'string', num_results: 'number?' },
    examples: ['web_search: Sage release 0.4.9'],
    enabled: true,
    usage_count: 24,
    source: 'builtin',
  },
  {
    name: 'create_agent',
    description: '派生后台 subagent 处理异步任务。',
    triggers: ['派生子代理', 'subagent'],
    parameters: { goal: 'string', model: 'string?' },
    examples: [],
    enabled: false,
    usage_count: 0,
    source: 'builtin',
  },
  {
    name: 'office_create',
    description: '创建 Office 文档 (pptx/docx/xlsx), 走 staging 流程。',
    triggers: ['建 PPT', '做 Excel', '写文档'],
    parameters: { doc_type: 'ppt|word|excel', title: 'string', template_id: 'string?' },
    examples: ['office_create: doc_type=word title=综述报告'],
    enabled: true,
    usage_count: 9,
    source: 'skillmd',
    base_dir: '/skills/office_create',
    version: '0.3.1',
  },
  {
    name: 'schedule_task',
    description: '调度周期性任务, cron 表达式。',
    triggers: ['定时', 'cron', '每隔'],
    parameters: { name: 'string', cron: 'string', action: 'string' },
    examples: ['schedule_task: cron="0 9 * * *" action=report'],
    enabled: true,
    usage_count: 11,
    source: 'skillmd',
    base_dir: '/skills/schedule_task',
    version: '0.1.4',
  },
  {
    name: 'memory_search',
    description: '在四层记忆中按语义检索, 返回 top-K。',
    triggers: ['记忆搜索', '回忆'],
    parameters: {
      query: 'string',
      layers: 'episodic|semantic|working|session_summary',
      top_k: 'number?',
    },
    examples: ['memory_search: layers=semantic'],
    enabled: true,
    usage_count: 33,
    source: 'skillmd',
    base_dir: '/skills/memory_search',
    version: '0.2.0',
  },
];

// =========================================================================
// Orchestration demo 数据
// =========================================================================

const LANE_BASE = NOW - 1000 * 60 * 30; // 30min ago
const HEARTBEAT_BASE = NOW - 1000 * 5; // 5s ago = fresh

export const DEMO_LANES: Lane[] = [
  {
    lane_id: 'lane-demo-001',
    task_id: 'task-demo-001',
    agent_id: 'planner',
    status: 'running',
    created_at: LANE_BASE,
    started_at: LANE_BASE + 1000,
    completed_at: null,
    worktree: '/tmp/worktrees/lane-001',
    heartbeat: {
      last_ping_at: HEARTBEAT_BASE,
      transport_alive: true,
      status: 'healthy',
    },
    error: null,
    permission_preset: 'workspace_write',
    metadata: { goal: '调研大模型医学应用进展并生成综述报告' },
  },
  {
    lane_id: 'lane-demo-002',
    task_id: 'task-demo-002',
    agent_id: 'executor-a',
    status: 'succeeded',
    created_at: LANE_BASE - 1000 * 60 * 5,
    started_at: LANE_BASE - 1000 * 60 * 5 + 500,
    completed_at: LANE_BASE - 1000 * 60 * 2,
    worktree: '/tmp/worktrees/lane-002',
    heartbeat: null,
    error: null,
    permission_preset: 'workspace_write',
    metadata: { goal: '文献筛选: 23 篇核心文献字段提取' },
  },
  {
    lane_id: 'lane-demo-003',
    task_id: 'task-demo-003',
    agent_id: 'executor-b',
    status: 'blocked',
    created_at: LANE_BASE - 1000 * 60 * 10,
    started_at: LANE_BASE - 1000 * 60 * 10 + 200,
    completed_at: null,
    worktree: '/tmp/worktrees/lane-003',
    heartbeat: {
      last_ping_at: HEARTBEAT_BASE - 1000 * 60 * 2,
      transport_alive: true,
      status: 'stalled',
    },
    error: null,
    permission_preset: 'workspace_write',
    metadata: { goal: '生成文献对比表 (等待 Reviewer 反馈)' },
  },
  {
    lane_id: 'lane-demo-004',
    task_id: 'task-demo-004',
    agent_id: 'reviewer',
    status: 'failed',
    created_at: LANE_BASE - 1000 * 60 * 20,
    started_at: LANE_BASE - 1000 * 60 * 20 + 100,
    completed_at: LANE_BASE - 1000 * 60 * 15,
    worktree: null,
    heartbeat: null,
    error: 'context length exceeded (32k tokens)',
    permission_preset: 'read_only',
    metadata: { goal: '终审文献对比表与综述报告产物' },
  },
];

export const DEMO_LANE_BOARD: LaneBoardSnapshot = {
  schema_version: '1',
  generated_at: NOW,
  generated_by: 'demo',
  view: 'ops_full',
  active: [
    {
      lane_id: 'lane-demo-001',
      task_id: 'task-demo-001',
      agent_id: 'planner',
      status: 'running',
      freshness: {
        lane_id: 'lane-demo-001',
        last_heartbeat_at: HEARTBEAT_BASE,
        age_ms: 5000,
        level: 'fresh',
        reasons: [],
      },
      heartbeat_status: 'healthy',
      last_event_at: HEARTBEAT_BASE,
      last_event_type: 'lane.running',
    },
  ],
  blocked: [
    {
      lane_id: 'lane-demo-003',
      task_id: 'task-demo-003',
      agent_id: 'executor-b',
      status: 'blocked',
      freshness: {
        lane_id: 'lane-demo-003',
        last_heartbeat_at: HEARTBEAT_BASE - 1000 * 60 * 2,
        age_ms: 120000,
        level: 'stale',
        reasons: ['heartbeat age > 60s'],
      },
      heartbeat_status: 'stalled',
      last_event_at: HEARTBEAT_BASE - 1000 * 60 * 2,
      last_event_type: 'lane.blocked',
    },
  ],
  finished: [
    {
      lane_id: 'lane-demo-002',
      task_id: 'task-demo-002',
      agent_id: 'executor-a',
      status: 'succeeded',
      freshness: {
        lane_id: 'lane-demo-002',
        last_heartbeat_at: null,
        age_ms: null,
        level: 'fresh',
        reasons: [],
      },
      heartbeat_status: null,
      last_event_at: LANE_BASE - 1000 * 60 * 2,
      last_event_type: 'lane.succeeded',
    },
    {
      lane_id: 'lane-demo-004',
      task_id: 'task-demo-004',
      agent_id: 'reviewer',
      status: 'failed',
      freshness: {
        lane_id: 'lane-demo-004',
        last_heartbeat_at: null,
        age_ms: null,
        level: 'fresh',
        reasons: [],
      },
      heartbeat_status: null,
      last_event_at: LANE_BASE - 1000 * 60 * 15,
      last_event_type: 'lane.failed',
    },
  ],
  freshness_summary: {
    total: 4,
    fresh: 3,
    stale: 1,
    dead: 0,
    overall_level: 'stale',
  },
};

export const DEMO_LANE_EVENTS: LaneEvent[] = [
  {
    event_id: 'evt-001',
    event_type: 'lane.started',
    lane_id: 'lane-demo-001',
    task_id: 'task-demo-001',
    agent_id: 'planner',
    timestamp: LANE_BASE + 1000,
    provenance: 'LiveLane',
    metadata: {},
  },
  {
    event_id: 'evt-002',
    event_type: 'lane.running',
    lane_id: 'lane-demo-001',
    task_id: 'task-demo-001',
    agent_id: 'planner',
    timestamp: HEARTBEAT_BASE,
    provenance: 'Heartbeat',
    metadata: { iteration: 3 },
  },
  {
    event_id: 'evt-003',
    event_type: 'lane.blocked',
    lane_id: 'lane-demo-003',
    task_id: 'task-demo-003',
    agent_id: 'executor-b',
    timestamp: HEARTBEAT_BASE - 1000 * 60 * 2,
    provenance: 'Manual',
    metadata: { reason: 'waiting_for_reviewer' },
  },
];

// =========================================================================
// Part 2 (2026-08-27): 中央通道注册表
//
// desktopInvoke.invoke() 顶部在演示模式下先查这里的注册表, 命中即返回,
// 未命中通道 fallthrough (后端已关, 各 client 既有降级路径消化错误).
// 时间戳单位: Session/Message/Memory 用毫秒; ScheduledTask/EvolutionLog/
// Office/MCP 用秒 (与后端惯例一致).
// =========================================================================

/** 演示工作区路径 (Office 页前置: workspace_get 必须返回非空 binding) */
export const DEMO_WORKSPACE_PATH = '/home/fz/sage-workspace';

const NOW_S = Math.floor(NOW / 1000);

function demoUUID(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      const v = c === 'x' ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }
}

function asStr(v: unknown, fallback = ''): string {
  return typeof v === 'string' ? v : fallback;
}

function asNum(v: unknown, fallback = 0): number {
  return typeof v === 'number' && Number.isFinite(v) ? v : fallback;
}

// ─────────────────────────────────────────────────────────────────────────
// 会话 (毫秒时间戳; id 必须 UUID 格式, chatApi 有严格正则校验)
// ─────────────────────────────────────────────────────────────────────────

export const DEMO_SESSION_SURVEY_ID = '7f3a9c1e-5b2d-4e8a-9c6f-1d2e3f4a5b6c';
export const DEMO_SESSION_PPT_ID = 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d';
export const DEMO_SESSION_MEETING_ID = 'c9d8e7f6-a5b4-4c3d-9e8f-7a6b5c4d3e2f';

/** 聊天流脚本的最终回复 (demoChatScript 的 done 事件携带完整内容) */
export const DEMO_SURVEY_REPORT_MD = `## 文献调研：大模型医学应用进展

### 调研范围
检索 PubMed、arXiv、IEEE Xplore 近三年文献，初检命中 **86 篇**，经去重与年份筛选保留 **23 篇核心文献**，其中近三年来源占比 **74%**。

### 核心文献分布

| 方向 | 篇数 | 代表工作 |
| --- | ---: | --- |
| 临床诊断辅助 | 9 | Med-PaLM 2 |
| 医学影像分析 | 7 | BiomedCLIP |
| 药物研发加速 | 4 | DrugGPT |
| 隐私与安全 | 3 | DP-MedLLM |

### 关键发现
1. **临床诊断辅助**最成熟：Med-PaLM 2 在 MedQA 多专科问答基准上中位准确率 **86.5%**
2. **医学影像分析**以 BiomedCLIP 类对比预训练为主流，较监督基线平均提升 **+9.2%**
3. **药物研发加速**商业化最快：候选分子平均筛选成本下降 **37%**

### 研究空白
- 低资源语言与长尾病种上的评测不足
- 隐私合规（HIPAA）与幻觉率仍是临床落地最大障碍

### 产物清单
- 文献对比表：文献对比表-23篇核心文献.xlsx（2 个工作表：核心文献、年份分布）
- 综述报告：文献综述报告-大模型医学应用.docx（6 章节）
`;

const demoSessions: Session[] = [
  {
    id: DEMO_SESSION_SURVEY_ID,
    title: '文献调研：大模型医学应用',
    created_at: NOW - 3600_000 * 3,
    updated_at: NOW - 3600_000 * 3,
    last_message_at: NOW - 3600_000 * 3,
    message_count: 2,
    is_pinned: true,
  },
  {
    id: DEMO_SESSION_PPT_ID,
    title: '生成产品发布会 PPT',
    created_at: NOW - 3600_000 * 26,
    updated_at: NOW - 3600_000 * 26,
    last_message_at: NOW - 3600_000 * 26,
    message_count: 2,
    is_pinned: false,
  },
  {
    id: DEMO_SESSION_MEETING_ID,
    title: '会议行动项提取',
    created_at: NOW - 86400_000 * 3,
    updated_at: NOW - 86400_000 * 3,
    last_message_at: NOW - 86400_000 * 3,
    message_count: 2,
    is_pinned: false,
  },
];

const demoMessages = new Map<string, Message[]>([
  [
    DEMO_SESSION_SURVEY_ID,
    [
      {
        id: 'msg-survey-001',
        session_id: DEMO_SESSION_SURVEY_ID,
        role: 'user',
        content: '近三年大模型在医学领域的应用，有哪些方向值得做文献调研？',
        created_at: NOW - 3600_000 * 3,
      },
      {
        id: 'msg-survey-002',
        session_id: DEMO_SESSION_SURVEY_ID,
        role: 'assistant',
        content:
          '建议聚焦三个方向：① 临床诊断辅助（文献量最大，近三年 48 篇）② 医学影像分析（方法迭代最快）③ 药物研发加速（商业价值最高）。\n\n临床诊断辅助已有 86 条初检结果，可以直接进入筛选。',
        created_at: NOW - 3600_000 * 3 + 4000,
        model: 'qwen2.5-72b-instruct',
      },
    ],
  ],
  [
    DEMO_SESSION_PPT_ID,
    [
      {
        id: 'msg-ppt-001',
        session_id: DEMO_SESSION_PPT_ID,
        role: 'user',
        content: '帮我生成一份产品发布会 PPT，重点介绍新的记忆系统',
        created_at: NOW - 3600_000 * 26,
      },
      {
        id: 'msg-ppt-002',
        session_id: DEMO_SESSION_PPT_ID,
        role: 'assistant',
        content:
          '已生成《产品发布会-0827.pptx》（5 页）：封面、痛点、方案、实战场景、路线图。\n\n可以在 Office 文档中查看，也可以让我继续调整内容。',
        created_at: NOW - 3600_000 * 26 + 6000,
        model: 'qwen2.5-72b-instruct',
        tool_calls: [{ name: 'office_create', args: {} }],
      },
    ],
  ],
  [
    DEMO_SESSION_MEETING_ID,
    [
      {
        id: 'msg-meet-001',
        session_id: DEMO_SESSION_MEETING_ID,
        role: 'user',
        content: '把昨天产品周会的行动项整理出来',
        created_at: NOW - 86400_000 * 3,
      },
      {
        id: 'msg-meet-002',
        session_id: DEMO_SESSION_MEETING_ID,
        role: 'assistant',
        content:
          '昨天产品周会的行动项：\n\n1. **编排 GA 收尾**：补齐 Reviewer 超时重试，负责人 A，截止周五\n2. **记忆二期评审**：整理四层架构容量数据，负责人 B，下周一上会\n3. **文献综述**：23 篇核心文献的综述初稿周五前完成，负责人 C，周五组会汇报',
        created_at: NOW - 86400_000 * 3 + 5000,
        model: 'qwen2.5-72b-instruct',
      },
    ],
  ],
]);

// ─────────────────────────────────────────────────────────────────────────
// Agents (5 个 profile, role 限 4 种枚举)
// ─────────────────────────────────────────────────────────────────────────

const DEMO_AGENTS: AgentProfile[] = [
  {
    id: 'planner',
    name: 'Planner',
    role: 'coordinator',
    description: '任务拆解与拓扑调度，按依赖关系生成执行计划',
    system_prompt: '你是调度规划器，负责把用户目标拆解为可独立执行的子任务并标注依赖。',
    tools: ['create_plan', 'assign_task', 'read_file'],
    memory_access: ['semantic', 'episodic'],
    model_config: { model: 'qwen2.5-72b-instruct', temperature: 0.3, max_tokens: 4096 },
    max_iterations: 10,
    enabled: true,
    updated_at: NOW_S - 86400 * 2,
  },
  {
    id: 'executor-a',
    name: 'Executor A',
    role: 'coder',
    description: '数据处理与脚本执行，负责汇总统计类任务',
    system_prompt: '你是数据执行代理 A，擅长读取 CSV/Excel 并用脚本做聚合统计。',
    tools: ['read_file', 'bash', 'edit_file'],
    memory_access: ['working'],
    model_config: { model: 'qwen2.5-72b-instruct', temperature: 0.2, max_tokens: 8192 },
    max_iterations: 12,
    enabled: true,
    updated_at: NOW_S - 86400,
  },
  {
    id: 'executor-b',
    name: 'Executor B',
    role: 'researcher',
    description: '图表渲染与调研分析，输出可视化产物',
    system_prompt: '你是可视化执行代理 B，负责生成趋势图与对比基线。',
    tools: ['read_file', 'web_search', 'write_file'],
    memory_access: ['working', 'episodic'],
    model_config: { model: 'qwen2.5-72b-instruct', temperature: 0.4, max_tokens: 8192 },
    max_iterations: 12,
    enabled: true,
    updated_at: NOW_S - 86400 * 3,
  },
  {
    id: 'reviewer',
    name: 'Reviewer',
    role: 'researcher',
    description: '质量门控：对执行器产物做断言式审查',
    system_prompt: '你是审查代理，对每个产物执行断言检查并给出通过/返工结论。',
    tools: ['read_file', 'assert'],
    memory_access: ['semantic'],
    model_config: { model: 'qwen2.5-72b-instruct', temperature: 0.1, max_tokens: 4096 },
    max_iterations: 6,
    enabled: true,
    updated_at: NOW_S - 3600 * 20,
  },
  {
    id: 'memory-manager',
    name: 'Memory Manager',
    role: 'memory_manager',
    description: '记忆沉淀与修剪，管理四层记忆生命周期',
    system_prompt: '你是记忆管理器，负责从会话中提取偏好并定期修剪低重要性记忆。',
    tools: ['memory_search', 'memory_save', 'memory_prune'],
    memory_access: ['episodic', 'semantic', 'working', 'session_summary'],
    model_config: { model: 'qwen2.5-7b-instruct', temperature: 0.2, max_tokens: 2048 },
    max_iterations: 5,
    enabled: false,
    updated_at: NOW_S - 86400 * 6,
  },
];

// ─────────────────────────────────────────────────────────────────────────
// 进化日志 (秒时间戳; 接口与 EvolutionLog.tsx 本地接口同形, id 是 string)
// ─────────────────────────────────────────────────────────────────────────

interface DemoEvolutionLog {
  id: string;
  evolution_type: string;
  description: string;
  before_state: string | null;
  after_state: string | null;
  trigger_type: string;
  trigger_condition: string | null;
  status: string;
  error_message: string | null;
  tokens_used: number | null;
  created_at: number;
  completed_at: number | null;
}

const DEMO_EVOLUTION_LOGS: DemoEvolutionLog[] = [
  {
    id: 'evo-101',
    evolution_type: 'daily_summary',
    description: '生成 2026-08-26 每日摘要：汇总 12 个会话、4 次编排运行，提炼 5 条新偏好',
    before_state: null,
    after_state: 'daily-summary-2026-08-26.md',
    trigger_type: 'scheduled',
    trigger_condition: 'cron 0 23 * * *',
    status: 'completed',
    error_message: null,
    tokens_used: 1840,
    created_at: NOW_S - 3600 * 14,
    completed_at: NOW_S - 3600 * 14 + 42,
  },
  {
    id: 'evo-102',
    evolution_type: 'preference_learning',
    description: '学到偏好「输出代码使用中文注释」（3 个会话持续出现），已升级为系统默认',
    before_state: '置信度 0.71',
    after_state: '置信度 0.94 · 系统默认',
    trigger_type: 'conversation',
    trigger_condition: null,
    status: 'completed',
    error_message: null,
    tokens_used: 960,
    created_at: NOW_S - 3600 * 5,
    completed_at: NOW_S - 3600 * 5 + 18,
  },
  {
    id: 'evo-103',
    evolution_type: 'memory_pruning',
    description: '修剪 importance < 3 的 working 记忆 14 条，保留 96 条高价值条目',
    before_state: 'working 记忆 110 条',
    after_state: 'working 记忆 96 条',
    trigger_type: 'scheduled',
    trigger_condition: 'cron 0 3 * * *',
    status: 'completed',
    error_message: null,
    tokens_used: null,
    created_at: NOW_S - 86400,
    completed_at: NOW_S - 86400 + 8,
  },
  {
    id: 'evo-104',
    evolution_type: 'importance_reevaluation',
    description: '对 32 条记忆重估重要性：近 7 天被访问条目的权重平均 +0.8',
    before_state: '平均 importance 4.2',
    after_state: '平均 importance 5.0',
    trigger_type: 'scheduled',
    trigger_condition: null,
    status: 'completed',
    error_message: null,
    tokens_used: 1210,
    created_at: NOW_S - 86400 * 2,
    completed_at: NOW_S - 86400 * 2 + 35,
  },
  {
    id: 'evo-105',
    evolution_type: 'memory_pruning',
    description: '尝试将 session summaries 沉淀到 semantic 层',
    before_state: null,
    after_state: null,
    trigger_type: 'threshold',
    trigger_condition: 'summary_count > 50',
    status: 'failed',
    error_message: 'LLM request timeout after 30s',
    tokens_used: 480,
    created_at: NOW_S - 86400 * 3,
    completed_at: NOW_S - 86400 * 3 + 30,
  },
  {
    id: 'evo-106',
    evolution_type: 'daily_summary',
    description: '生成 2026-08-24 每日摘要：汇总 9 个会话，突出 Office 集成 M0 进展',
    before_state: null,
    after_state: 'daily-summary-2026-08-24.md',
    trigger_type: 'scheduled',
    trigger_condition: 'cron 0 23 * * *',
    status: 'completed',
    error_message: null,
    tokens_used: 1720,
    created_at: NOW_S - 86400 * 3 + 3600,
    completed_at: NOW_S - 86400 * 3 + 3600 + 39,
  },
];

// ─────────────────────────────────────────────────────────────────────────
// Office 文档 (秒时间戳)
// ─────────────────────────────────────────────────────────────────────────

const DEMO_OFFICE_DOCS: OfficeDocumentSummary[] = [
  {
    id: 'of-1',
    workspace_path: DEMO_WORKSPACE_PATH,
    doc_type: 'word',
    original_filename: '文献综述报告-大模型医学应用.docx',
    generated_filename: '文献综述报告-大模型医学应用.docx',
    status: 'parsed',
    created_at: NOW_S - 3600 * 26,
    updated_at: NOW_S - 3600 * 2,
    metadata: { page_count: 6, paragraph_count: 58, table_count: 2, file_size_bytes: 42381 },
  },
  {
    id: 'of-2',
    workspace_path: DEMO_WORKSPACE_PATH,
    doc_type: 'excel',
    original_filename: '文献对比表-23篇核心文献.xlsx',
    generated_filename: '文献对比表-23篇核心文献.xlsx',
    status: 'parsed',
    created_at: NOW_S - 86400,
    updated_at: NOW_S - 3600 * 20,
    metadata: { sheet_count: 2, file_size_bytes: 86528 },
  },
  {
    id: 'of-3',
    workspace_path: DEMO_WORKSPACE_PATH,
    doc_type: 'ppt',
    original_filename: null,
    generated_filename: '产品发布会-0827.pptx',
    status: 'generated',
    created_at: NOW_S - 86400 * 2,
    updated_at: NOW_S - 86400 * 2 + 600,
    metadata: { page_count: 5, file_size_bytes: 2516582 },
  },
];

const DEMO_WORD_READ: OfficeWordReadResult = {
  summary: DEMO_OFFICE_DOCS[0],
  paragraphs: [
    { style: 'Heading 1', text: '文献综述报告：大模型医学应用进展', level: 1 },
    { style: 'Heading 2', text: '1. 研究背景', level: 2 },
    {
      style: 'Normal',
      text: '近三年，大语言模型在医学领域的应用呈爆发式增长。临床诊断辅助方向近三年 PubMed 收录 48 篇，医学影像分析方法迭代最快。',
      level: 0,
    },
    { style: 'Heading 2', text: '2. 关键发现', level: 2 },
    {
      style: 'Normal',
      text: 'Med-PaLM 2 在 MedQA 基准上中位准确率 86.5%；BiomedCLIP 类对比预训练使医学影像任务较监督基线平均提升 +9.2%。',
      level: 0,
    },
    { style: 'Heading 2', text: '3. 研究空白', level: 2 },
    {
      style: 'Normal',
      text: '低资源语言与长尾病种的评测不足；隐私合规（HIPAA）与幻觉率仍是临床落地最大障碍。',
      level: 0,
    },
    { style: 'Heading 2', text: '4. 结论', level: 2 },
    {
      style: 'Normal',
      text: '临床诊断辅助最成熟，药物研发加速商业化最快（候选分子平均筛选成本下降 37%），隐私与安全方向需持续关注。',
      level: 0,
    },
  ],
  tables: [
    {
      rows: [
        ['方向', '篇数', '代表工作'],
        ['临床诊断辅助', '9', 'Med-PaLM 2'],
        ['医学影像分析', '7', 'BiomedCLIP'],
        ['药物研发加速', '4', 'DrugGPT'],
        ['隐私与安全', '3', 'DP-MedLLM'],
      ],
    },
  ],
  images: 1,
};

const DEMO_EXCEL_READ: OfficeExcelReadResult = {
  summary: DEMO_OFFICE_DOCS[1],
  sheets: [
    {
      name: '核心文献',
      rows: [
        ['序号', '标题', '方向', '方法', '数据集', '结论'],
        [
          '01',
          'Med-PaLM 2',
          '临床诊断辅助',
          '指令微调 + 专家反馈',
          'MedQA / MedMCQA',
          '中位准确率 86.5%',
        ],
        ['02', 'BiomedCLIP', '医学影像分析', '对比预训练', 'PMC-15M', '较监督基线 +9.2%'],
        ['03', 'DrugGPT', '药物研发加速', '分子生成', 'ChEMBL', '筛选成本 -37%'],
        ['04', 'DP-MedLLM', '隐私与安全', '差分隐私微调', 'MIMIC-III', '满足 HIPAA 要求'],
      ],
      max_row: 5,
      max_col: 6,
    },
    {
      name: '年份分布',
      rows: [
        ['年份', '篇数'],
        ['2024', '6'],
        ['2025', '9'],
        ['2026', '8'],
      ],
      max_row: 4,
      max_col: 2,
    },
  ],
};

const DEMO_PPT_READ: OfficePptReadResult = {
  summary: DEMO_OFFICE_DOCS[2],
  slides: [
    {
      index: 1,
      title: 'Sage 0.4.10 产品发布会',
      text_blocks: ['多智能体编排 · 记忆系统 · Office 集成'],
      table_count: 0,
      image_count: 1,
      notes: '开场：介绍本次发布主题',
    },
    {
      index: 2,
      title: '痛点',
      text_blocks: ['重复任务分散注意力', '跨会话上下文丢失'],
      table_count: 0,
      image_count: 0,
      notes: null,
    },
    {
      index: 3,
      title: '解决方案',
      text_blocks: [
        'Planner / Executor / Reviewer 三角色编排',
        '四层记忆自动沉淀',
        'Office 文档读写一体',
      ],
      table_count: 0,
      image_count: 1,
      notes: '展示编排拓扑图',
    },
    {
      index: 4,
      title: '实战场景',
      text_blocks: ['实战场景：文献调研 → 自动生成综述报告'],
      table_count: 1,
      image_count: 0,
      notes: '实战场景走查 3 分钟',
    },
    {
      index: 5,
      title: '路线图',
      text_blocks: ['0.5.0：MCP 生态扩展', '0.6.0：多端同步'],
      table_count: 0,
      image_count: 0,
      notes: null,
    },
  ],
};

// ─────────────────────────────────────────────────────────────────────────
// 用量统计 / 会话摘要 / 定时任务 / 技能执行输出
// ─────────────────────────────────────────────────────────────────────────

const DEMO_USAGE: UsageSummary = {
  totals: {
    requests: 1284,
    prompt_tokens: 3412800,
    completion_tokens: 892400,
    estimated_cost_usd: 12.84,
  },
  by_model: [
    {
      model: 'qwen2.5-72b-instruct',
      requests: 962,
      prompt_tokens: 2610000,
      completion_tokens: 701200,
      estimated_cost_usd: 9.62,
    },
    {
      model: 'qwen2.5-7b-instruct',
      requests: 322,
      prompt_tokens: 802800,
      completion_tokens: 191200,
      estimated_cost_usd: 3.22,
    },
  ],
  today: {
    requests: 47,
    prompt_tokens: 128400,
    completion_tokens: 36200,
    estimated_cost_usd: 0.52,
  },
};

/** 文献调研会话的 session_summary 记忆 (get_session_summaries 专用; 含 1 条 failed 展示徽章) */
const DEMO_SURVEY_SUMMARIES: Memory[] = [
  {
    id: 'sum-001',
    content:
      '用户讨论了大模型医学应用文献调研的目标：1) 检索近三年 PubMed/arXiv 文献并去重；2) 筛选 23 篇核心文献并提取方法/数据集/结论；3) 生成对比表与综述报告。',
    summary: '文献调研与综述报告规划',
    memory_type: 'session_summary',
    layer: 'session_summary',
    source: 'session_summary',
    session_id: DEMO_SESSION_SURVEY_ID,
    status: 'ready',
    importance: 6,
    tags: ['session-summary', '调研'],
    created_at: NOW - 3600_000 * 3,
    created_at_ms: NOW - 3600_000 * 3,
    access_count: 1,
  },
  {
    id: 'sum-002',
    content: '首次尝试提取纳入排除标准讨论摘要。',
    memory_type: 'session_summary',
    layer: 'session_summary',
    source: 'session_summary',
    session_id: DEMO_SESSION_SURVEY_ID,
    status: 'failed',
    error_message: 'LLM request timed out (30s)',
    importance: 3,
    tags: ['session-summary'],
    created_at: NOW - 3600_000 * 26,
    created_at_ms: NOW - 3600_000 * 26,
    access_count: 0,
  },
];

const DEMO_SCHEDULED_TASKS: ScheduledTask[] = [
  {
    id: 'sched-001',
    name: '每周文献动态跟踪',
    type: 'recurring',
    schedule: { kind: 'recurring', cron: '0 9 * * 1' },
    session_id: DEMO_SESSION_SURVEY_ID,
    content: '检索近一周新增文献，推送对比表增量更新到会话',
    enabled: true,
    last_run: NOW_S - 86400,
    next_run: NOW_S + 3600 * 14,
    created_at: NOW_S - 86400 * 12,
  },
  {
    id: 'sched-002',
    name: '一次性提醒：综述初稿组会汇报',
    type: 'once',
    schedule: { kind: 'once', at: NOW_S + 86400 },
    session_id: DEMO_SESSION_SURVEY_ID,
    content: '检查综述报告初稿是否覆盖全部 23 篇核心文献',
    enabled: true,
    last_run: null,
    next_run: NOW_S + 86400,
    created_at: NOW_S - 3600 * 5,
  },
];

const DEMO_SKILL_RUN_OUTPUT = `# 2026-08-27 日报

## 今日会话
- 共发起 12 个会话（+20% vs 上周均值）
- 平均会话时长 8.4 分钟

## 完成任务
- [x] 修复订单服务缓存击穿
- [x] 评审 PR #382
- [x] 整理知识库标签

## 记忆沉淀
- 新增 5 条偏好
- 复用 12 条历史记忆

## 明日建议
- 推进 release/0.4.10 元数据对齐
`;

// ─────────────────────────────────────────────────────────────────────────
// 可变状态 (写操作作用于这些集合, 演示期间增删可见)
// ─────────────────────────────────────────────────────────────────────────

let demoSkills: Skill[] = [...DEMO_SKILLS];
let demoAgents: AgentProfile[] = [...DEMO_AGENTS];
let demoOfficeDocs: OfficeDocumentSummary[] = [...DEMO_OFFICE_DOCS];
let demoMemories: Memory[] = [...DEMO_MEMORIES];
let demoScheduled: ScheduledTask[] = [...DEMO_SCHEDULED_TASKS];

// Preferences KV (get_preference / set_preference): 后端不在, 用内存 Map 顶替。
// current_session_id 特判返回演示文献调研会话, 首屏直接落到聊天页。
const demoPreferences = new Map<string, string>();

// ─────────────────────────────────────────────────────────────────────────
// 通道注册表
//
// 绝不注册 get_settings / set_settings — 保持真实设置 (含演示开关本身).
// ─────────────────────────────────────────────────────────────────────────

const demoHandlers: Record<string, (args: Record<string, unknown>) => unknown> = {
  // ── Preferences (KV) ──
  // 后端不在 → 内存 KV。未写入过的键返回 value:null, 调用方走各自默认值
  // (与后端未设置时的行为一致, 如 theme_mode / permission_mode)。
  get_preference: (args) => {
    const key = asStr(args.key);
    const stored = demoPreferences.get(key);
    if (stored !== undefined) {
      return { value: stored, value_type: 'string', category: 'ui' };
    }
    if (key === 'current_session_id') {
      return { value: DEMO_SESSION_SURVEY_ID, value_type: 'string', category: 'ui' };
    }
    return { value: null, value_type: 'string', category: 'ui' };
  },
  set_preference: (args) => {
    const key = asStr(args.key);
    const value = typeof args.value === 'string' ? args.value : '';
    demoPreferences.set(key, value);
    return { ok: true };
  },

  // ── 会话 ──
  list_sessions: () => [...demoSessions],

  create_session: (args) => {
    const nowMs = Date.now();
    const session: Session = {
      id: demoUUID(),
      title: asStr(args.title) || '新会话',
      created_at: nowMs,
      updated_at: nowMs,
      last_message_at: null,
      message_count: 0,
      is_pinned: false,
    };
    demoSessions.unshift(session);
    demoMessages.set(session.id, []);
    return session;
  },

  get_session: (args) => {
    const id = asStr(args.sessionId) || asStr(args.id);
    return demoSessions.find((s) => s.id === id) ?? null;
  },

  delete_session: (args) => {
    const id = asStr(args.id) || asStr(args.sessionId);
    const index = demoSessions.findIndex((s) => s.id === id);
    if (index >= 0) demoSessions.splice(index, 1);
    demoMessages.delete(id);
    return { ok: true };
  },

  get_messages: (args) => [...(demoMessages.get(asStr(args.sessionId)) ?? [])],

  delete_message: (args) => {
    const messageId = asStr(args.messageId) || asStr(args.id);
    for (const [sessionId, list] of demoMessages) {
      const index = list.findIndex((m) => m.id === messageId);
      if (index >= 0) {
        list.splice(index, 1);
        const session = demoSessions.find((s) => s.id === sessionId);
        if (session) session.message_count = Math.max(0, session.message_count - 1);
        break;
      }
    }
    return { ok: true };
  },

  session_compact: (args) => {
    const id = asStr(args.sessionId) || asStr(args.id);
    const list = demoMessages.get(id) ?? [];
    const before = list.length;
    const after = Math.min(before, 2);
    const result: SessionCompactResult = {
      ok: true,
      compacted: before > after,
      before,
      after,
      removed: Math.max(0, before - after),
    };
    if (before > after) demoMessages.set(id, [list[0], list[list.length - 1]]);
    return result;
  },

  export_session_html: (args) => {
    const id = asStr(args.sessionId) || asStr(args.id);
    const session = demoSessions.find((s) => s.id === id);
    const list = demoMessages.get(id) ?? [];
    const escape = (text: string) =>
      text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const body = list
      .map((m) => `<h3>${escape(m.role)}</h3><div>${escape(m.content)}</div>`)
      .join('');
    const result: SessionExportResult = {
      html: `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${escape(session?.title ?? '会话导出')}</title></head><body><h1>${escape(session?.title ?? '')}</h1>${body}</body></html>`,
      filename: `sage-session-${id.slice(0, 8)}.html`,
      session_id: id,
      message_count: list.length,
      theme: 'auto',
    };
    return result;
  },

  // ── 记忆 ──
  get_memories: (args) => {
    const layer = asStr(args.memoryType) || 'all';
    const sessionId = asStr(args.sessionId);
    let list = demoMemories;
    if (layer && layer !== 'all') list = list.filter((m) => (m.layer ?? m.memory_type) === layer);
    if (sessionId) list = list.filter((m) => m.session_id === sessionId);
    const pageSize = Math.min(100, Math.max(1, asNum(args.pageSize, 20)));
    const offset =
      args.offset != null
        ? Math.max(0, asNum(args.offset, 0))
        : (Math.max(1, asNum(args.page, 1)) - 1) * pageSize;
    const items = list.slice(offset, offset + pageSize);
    const breakdown: Record<string, number> = {
      episodic: 0,
      semantic: 0,
      working: 0,
      session_summary: 0,
    };
    for (const m of list) {
      const key = m.layer ?? m.memory_type;
      if (key && key in breakdown) breakdown[key] += 1;
    }
    return {
      items,
      total: list.length,
      page: Math.max(1, asNum(args.page, 1)),
      page_size: pageSize,
      offset,
      layer: layer || 'all',
      source_breakdown: breakdown,
    };
  },

  search_memory: (args) => searchDemoMemories(asStr(args.query)),

  save_memory: (args) => {
    const nowMs = Date.now();
    const memoryType = args.memoryType === 'episodic' ? 'episodic' : 'semantic';
    const memory: Memory = {
      id: demoUUID(),
      content: asStr(args.content),
      memory_type: memoryType,
      layer: memoryType,
      source: memoryType,
      importance: Math.min(10, Math.max(0, asNum(args.importance, 5))),
      tags: Array.isArray(args.tags)
        ? (args.tags.filter((t) => typeof t === 'string') as string[])
        : [],
      created_at: nowMs,
      created_at_ms: nowMs,
      access_count: 0,
    };
    demoMemories = [memory, ...demoMemories];
    return memory;
  },

  delete_memory: (args) => {
    const id = asStr(args.id);
    demoMemories = demoMemories.filter((m) => m.id !== id);
    return { ok: true };
  },

  get_session_summaries: (args) => {
    const sessionId = asStr(args.sessionId);
    const items = DEMO_SURVEY_SUMMARIES.filter((m) => m.session_id === sessionId);
    return {
      session_id: sessionId,
      items,
      total: items.length,
      page: 1,
      page_size: 20,
      offset: 0,
    };
  },

  // ── 知识库 ──
  list_knowledge_docs: () => [...DEMO_KNOWLEDGE_DOCS],

  search_knowledge_docs: (args) => {
    const query = asStr(args.query).toLowerCase();
    return DEMO_KNOWLEDGE_DOCS.filter(
      (d) =>
        d.title.toLowerCase().includes(query) ||
        (d.description ?? '').toLowerCase().includes(query) ||
        (d.tags ?? []).some((t) => t.toLowerCase().includes(query)),
    );
  },

  // ── 技能 ──
  list_skills: () => [...demoSkills],

  toggle_skill: (args) => {
    const name = asStr(args.name);
    demoSkills = demoSkills.map((s) =>
      s.name === name
        ? { ...s, enabled: typeof args.enabled === 'boolean' ? args.enabled : !s.enabled }
        : s,
    );
    return demoSkills.find((s) => s.name === name) ?? null;
  },

  archive_skill: (args) => {
    const name = asStr(args.name);
    const archived = args.archived !== false;
    demoSkills = demoSkills.map((s) =>
      s.name === name ? { ...s, lifecycle: archived ? 'archived' : 'stale' } : s,
    );
    return demoSkills.find((s) => s.name === name) ?? null;
  },

  delete_skill: (args) => {
    const name = asStr(args.name);
    demoSkills = demoSkills.filter((s) => s.name !== name);
    const result: DeleteSkillResult = { deleted: true, name, base_dir: `/skills/${name}` };
    return result;
  },

  execute_skill: () => {
    const result: SkillExecuteResult = {
      success: true,
      content: DEMO_SKILL_RUN_OUTPUT,
      metadata: { duration_ms: 2340 },
    };
    return result;
  },

  list_slash_commands: () => ({
    commands: demoSkills
      .filter((s) => s.enabled && s.source === 'skillmd' && s.lifecycle !== 'archived')
      .map((s) => `/${s.name}`),
  }),

  list_skill_drafts: () => [],

  approve_skill_draft: () => ({ ok: true }),
  reject_skill_draft: () => ({ ok: true }),

  // ── Agents ──
  list_agents: () => [...demoAgents],

  toggle_agent: (args) => {
    const id = asStr(args.id) || asStr(args.agentId);
    demoAgents = demoAgents.map((a) =>
      a.id === id
        ? { ...a, enabled: typeof args.enabled === 'boolean' ? args.enabled : !a.enabled }
        : a,
    );
    return demoAgents.find((a) => a.id === id) ?? null;
  },

  update_agent: (args) => {
    const id = asStr(args.id) || asStr(args.agentId);
    const rawUpdate =
      args.update && typeof args.update === 'object'
        ? (args.update as Record<string, unknown>)
        : {};
    const patch = { ...rawUpdate };
    delete patch.id;
    demoAgents = demoAgents.map((a) => (a.id === id ? { ...a, ...patch, updated_at: NOW_S } : a));
    return demoAgents.find((a) => a.id === id) ?? null;
  },

  // ── 编排 ──
  orchestration_board: () => DEMO_LANE_BOARD,
  orchestration_list_lanes: () => [...DEMO_LANES],
  orchestration_get_lane: (args) =>
    DEMO_LANES.find((l) => l.lane_id === asStr(args.lane_id)) ?? null,
  orchestration_list_lane_events: (args) =>
    DEMO_LANE_EVENTS.filter((e) => e.lane_id === asStr(args.lane_id)),

  orchestration_create_lane: (args) => {
    const response: CreateLanesResponse = {
      ok: true,
      team_id: 'team-demo-01',
      lanes: DEMO_LANES.slice(0, 2),
      tasks: [
        {
          task_id: 'task-demo-001',
          name: asStr(args.goal) || '文献收集',
          description: '检索 PubMed/arXiv 并去重初筛',
          task_type: 'analysis',
          status: 'running',
          blocked_by: [],
          team_id: 'team-demo-01',
          agent_hint: 'executor-a',
        },
        {
          task_id: 'task-demo-002',
          name: '核心文献精读',
          description: '提取 23 篇文献的方法/数据集/结论',
          task_type: 'analysis',
          status: 'created',
          blocked_by: ['task-demo-001'],
          team_id: 'team-demo-01',
          agent_hint: 'executor-b',
        },
      ],
    };
    return response;
  },

  orchestration_cancel_lane: () => ({ ok: true }),
  orchestration_list_runs: () => [],
  orchestration_get_run: () => null,
  orchestration_cancel_run: () => ({ ok: true }),
  orchestration_update_plan: () => ({ ok: true }),

  // ── 定时任务 ──
  scheduled_list_tasks: () => [...demoScheduled],

  scheduled_create_task: (args) => {
    const input =
      args.input && typeof args.input === 'object' ? (args.input as Record<string, unknown>) : args;
    const task: ScheduledTask = {
      id: demoUUID(),
      name: asStr(input.name) || '定时任务',
      type: input.type === 'once' ? 'once' : 'recurring',
      schedule:
        input.schedule && typeof input.schedule === 'object'
          ? (input.schedule as ScheduledTask['schedule'])
          : { kind: 'recurring', cron: '0 9 * * *' },
      session_id: asStr(input.session_id) || DEMO_SESSION_SURVEY_ID,
      content: asStr(input.content),
      enabled: true,
      last_run: null,
      next_run: NOW_S + 3600 * 12,
      created_at: NOW_S,
    };
    demoScheduled = [...demoScheduled, task];
    return task;
  },

  scheduled_update_task: (args) => {
    const id = asStr(args.id);
    const changes =
      args.changes && typeof args.changes === 'object'
        ? (args.changes as Record<string, unknown>)
        : {};
    demoScheduled = demoScheduled.map((t) => (t.id === id ? { ...t, ...changes, id: t.id } : t));
    return demoScheduled.find((t) => t.id === id) ?? null;
  },

  scheduled_delete_task: (args) => {
    const id = asStr(args.id);
    demoScheduled = demoScheduled.filter((t) => t.id !== id);
    return null;
  },

  scheduled_run_task: (args) => {
    const id = asStr(args.id);
    demoScheduled = demoScheduled.map((t) => (t.id === id ? { ...t, last_run: NOW_S } : t));
    return demoScheduled.find((t) => t.id === id) ?? null;
  },

  // ── 用量 ──
  usage_summary: () => DEMO_USAGE,

  // ── Workspace (Office 页前置) ──
  workspace_get: (args) => ({
    binding: {
      session_id: asStr(args.sessionId) || DEMO_SESSION_SURVEY_ID,
      workspace_path: DEMO_WORKSPACE_PATH,
      generation: 3,
      activated_at: NOW_S - 86400,
      revoked_at: null,
    },
  }),

  workspace_bind: (args) => ({
    binding: {
      session_id: asStr(args.sessionId) || DEMO_SESSION_SURVEY_ID,
      workspace_path: asStr(args.workspacePath) || DEMO_WORKSPACE_PATH,
      generation: 4,
      activated_at: NOW_S,
      revoked_at: null,
    },
  }),

  workspace_revoke: () => ({ revoked: true, generation: 5 }),

  workspace_search_files: () => ({
    results: [
      {
        name: '文献清单-初筛-86篇.csv',
        kind: 'file',
        doc_type: null,
        doc_id: null,
        size_bytes: 48213,
        needs_import: false,
        source_path: `${DEMO_WORKSPACE_PATH}/data/文献清单-初筛-86篇.csv`,
      },
      {
        name: '文献综述报告-大模型医学应用.docx',
        kind: 'office-word',
        doc_type: 'word',
        doc_id: 'of-1',
        size_bytes: 42381,
        needs_import: false,
        source_path: null,
      },
      {
        name: '检索策略与纳入排除标准.pdf',
        kind: 'file',
        doc_type: null,
        doc_id: null,
        size_bytes: 1284500,
        needs_import: true,
        source_path: '/home/fz/Downloads/检索策略与纳入排除标准.pdf',
      },
    ],
    total: 3,
  }),

  // ── Office ──
  office_list_documents: () => ({ documents: [...demoOfficeDocs], total: demoOfficeDocs.length }),

  office_delete_document: (args) => {
    const docId = asStr(args.docId) || asStr(args.id);
    demoOfficeDocs = demoOfficeDocs.filter((d) => d.id !== docId);
    const result: OfficeDeleteResponse = { id: docId, deleted: true };
    return result;
  },

  office_word_read: () => DEMO_WORD_READ,
  office_excel_read: () => DEMO_EXCEL_READ,
  office_ppt_read: () => DEMO_PPT_READ,

  office_word_generate: (args) => {
    const workspacePath =
      asStr(args.workspace_path) || asStr(args.workspacePath) || DEMO_WORKSPACE_PATH;
    const filename = asStr(args.filename) || '文档.docx';
    const doc: OfficeDocumentSummary = {
      id: demoUUID(),
      workspace_path: workspacePath,
      doc_type: 'word',
      original_filename: null,
      generated_filename: filename,
      status: 'generated',
      created_at: NOW_S,
      updated_at: NOW_S,
      metadata: { paragraph_count: 12, table_count: 1, file_size_bytes: 24576 },
    };
    demoOfficeDocs = [doc, ...demoOfficeDocs];
    return { output_path: `${workspacePath}/${filename}`, filename, file_size_bytes: 24576 };
  },

  office_excel_generate: (args) => {
    const workspacePath =
      asStr(args.workspace_path) || asStr(args.workspacePath) || DEMO_WORKSPACE_PATH;
    const filename = asStr(args.filename) || '数据表.xlsx';
    const doc: OfficeDocumentSummary = {
      id: demoUUID(),
      workspace_path: workspacePath,
      doc_type: 'excel',
      original_filename: null,
      generated_filename: filename,
      status: 'generated',
      created_at: NOW_S,
      updated_at: NOW_S,
      metadata: { sheet_count: 1, file_size_bytes: 18432 },
    };
    demoOfficeDocs = [doc, ...demoOfficeDocs];
    return { output_path: `${workspacePath}/${filename}`, filename, file_size_bytes: 18432 };
  },

  office_ppt_generate: (args) => {
    const workspacePath =
      asStr(args.workspace_path) || asStr(args.workspacePath) || DEMO_WORKSPACE_PATH;
    const filename = asStr(args.filename) || '幻灯片.pptx';
    const doc: OfficeDocumentSummary = {
      id: demoUUID(),
      workspace_path: workspacePath,
      doc_type: 'ppt',
      original_filename: null,
      generated_filename: filename,
      status: 'generated',
      created_at: NOW_S,
      updated_at: NOW_S,
      metadata: { page_count: 4, file_size_bytes: 1048576 },
    };
    demoOfficeDocs = [doc, ...demoOfficeDocs];
    return { output_path: `${workspacePath}/${filename}`, filename, file_size_bytes: 1048576 };
  },

  // ── 进化 / 学习 ──
  trigger_learn: () => {
    const response: LearnResponse = { status: 'queued', message: '已加入后台审阅队列' };
    return response;
  },

  get_evolution_logs: (args) => {
    const offset = Math.max(0, asNum(args.offset, 0));
    const limit = Math.min(100, Math.max(1, asNum(args.limit, 20)));
    return DEMO_EVOLUTION_LOGS.slice(offset, offset + limit);
  },

  // ── MCP ──
  mcp_status: () => {
    const report: McpStatusReport = {
      generated_at: NOW_S,
      all_ready: true,
      degraded: false,
      failed_required: false,
      servers: [
        {
          name: 'filesystem',
          state: 'ready',
          tool_count: 6,
          last_error: null,
          since: NOW_S - 3600,
          required: false,
        },
      ],
    };
    return report;
  },

  mcp_servers: () => {
    const config: McpServerConfig = {
      name: 'filesystem',
      command: 'npx',
      args: ['-y', '@modelcontextprotocol/server-filesystem', DEMO_WORKSPACE_PATH],
      env: {},
      enabled: true,
      required: false,
      timeout_seconds: 30,
      builtin: false,
    };
    return { servers: [config] };
  },

  mcp_server_add: (args) => {
    const config: McpServerConfig = {
      name: asStr(args.name),
      command: asStr(args.command),
      args: Array.isArray(args.args)
        ? (args.args.filter((a) => typeof a === 'string') as string[])
        : [],
      env: {},
      enabled: true,
      required: args.required === true,
      timeout_seconds: 30,
      builtin: false,
    };
    return config;
  },

  mcp_server_update: (args) => {
    const config: McpServerConfig = {
      name: asStr(args.name),
      command: asStr(args.command),
      args: Array.isArray(args.args)
        ? (args.args.filter((a) => typeof a === 'string') as string[])
        : [],
      env: {},
      enabled: args.enabled !== false,
      required: args.required === true,
      timeout_seconds: 30,
      builtin: false,
    };
    return config;
  },

  mcp_server_delete: () => ({ ok: true }),

  // ── 主题 ──
  theme_list: () => [],
  theme_get: () => null,
  theme_save: (args) => ({ id: demoUUID(), ...args }),
  theme_delete: () => ({ ok: true }),

  // ── 流控制 ──
  interrupt_agent: () => ({ ok: true }),
  questions_answer: () => ({ ok: true }),
  permissions_answer: () => ({ ok: true }),
};

export interface DemoInvokeResult {
  hit: boolean;
  value?: unknown;
}

/** 中央通道查表: 命中返回 {hit:true, value}, 未命中 {hit:false} 走原通道. */
export function demoInvoke(cmd: string, args: Record<string, unknown>): DemoInvokeResult {
  const handler = demoHandlers[cmd];
  if (!handler) return { hit: false };
  return { hit: true, value: handler(args) };
}

export function searchDemoMemories(query: string, memoryType?: 'episodic' | 'semantic'): Memory[] {
  const lower = query.toLowerCase();
  return demoMemories.filter((m) => {
    if (memoryType && m.memory_type && m.memory_type !== memoryType) return false;
    return (
      m.content.toLowerCase().includes(lower) ||
      (m.summary?.toLowerCase().includes(lower) ?? false) ||
      m.tags.some((t) => t.toLowerCase().includes(lower))
    );
  });
}

/** 聊天脚本结束后把用户消息 + 助手回复写入会话历史 (含计数/时间/标题). */
export function demoAppendMessages(
  sessionId: string,
  userMessage: string,
  assistantContent: string,
): void {
  const list = demoMessages.get(sessionId) ?? [];
  const nowMs = Date.now();
  const userMessageItem: Message = {
    id: demoUUID(),
    session_id: sessionId,
    role: 'user',
    content: userMessage,
    created_at: nowMs,
  };
  const assistantMessageItem: Message = {
    id: demoUUID(),
    session_id: sessionId,
    role: 'assistant',
    content: assistantContent,
    created_at: nowMs + 1,
    model: 'qwen2.5-72b-instruct',
  };
  demoMessages.set(sessionId, [...list, userMessageItem, assistantMessageItem]);
  const session = demoSessions.find((s) => s.id === sessionId);
  if (session) {
    session.message_count = (session.message_count ?? 0) + 2;
    session.last_message_at = nowMs;
    session.updated_at = nowMs;
    if (session.title === '新会话') {
      session.title = userMessage.slice(0, 24) || '新会话';
    }
  }
}
