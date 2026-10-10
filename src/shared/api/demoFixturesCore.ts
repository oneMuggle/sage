import type { KnowledgeDoc, Lane, LaneBoardSnapshot, LaneEvent, Memory, Skill } from './types';

export const NOW = Date.now();

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
export const NOW_S = Math.floor(NOW / 1000);

/** P2-2 demo 技能审计台账的三个相对时间点（毫秒），让 demo 记录看起来是先后发生的 */
export const DEMO_AUDIT_T0 = NOW - 86_400_000 * 30;
export const DEMO_AUDIT_T1 = NOW - 86_400_000 * 7;
export const DEMO_AUDIT_T2 = NOW - 3_600_000 * 5;

export function demoUUID(): string {
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

export function asStr(v: unknown, fallback = ''): string {
  return typeof v === 'string' ? v : fallback;
}

export function asNum(v: unknown, fallback = 0): number {
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
