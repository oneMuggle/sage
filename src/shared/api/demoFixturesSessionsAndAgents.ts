import { DEMO_SESSION_MEETING_ID, DEMO_SESSION_PPT_ID, DEMO_SESSION_SURVEY_ID, NOW, NOW_S } from './demoFixturesCore';
import type { AgentProfile, Memory, Message, ScheduledTask, Session } from './types';
import type { UsageSummary } from './usageApi';

export const demoSessions: Session[] = [
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

export const demoMessages = new Map<string, Message[]>([
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

export const DEMO_AGENTS: AgentProfile[] = [
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

export interface DemoEvolutionLog {
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

export const DEMO_EVOLUTION_LOGS: DemoEvolutionLog[] = [
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


export const DEMO_USAGE: UsageSummary = {
  totals: {
    requests: 1284,
    prompt_tokens: 3412800,
    completion_tokens: 892400,
    cached_tokens: 2100000,
    cache_read_tokens: 1800000,
    cache_creation_tokens: 300000,
    estimated_cost_usd: 12.84,
    known_requests: 1284,
    unknown_requests: 0,
  },
  by_model: [
    {
      model: 'qwen2.5-72b-instruct',
      requests: 962,
      prompt_tokens: 2610000,
      completion_tokens: 701200,
      cached_tokens: 1700000,
      cache_read_tokens: 1450000,
      cache_creation_tokens: 250000,
      estimated_cost_usd: 9.62,
      known_requests: 962,
      unknown_requests: 0,
    },
    {
      model: 'qwen2.5-7b-instruct',
      requests: 322,
      prompt_tokens: 802800,
      completion_tokens: 191200,
      cached_tokens: 400000,
      cache_read_tokens: 350000,
      cache_creation_tokens: 50000,
      estimated_cost_usd: 3.22,
      known_requests: 322,
      unknown_requests: 0,
    },
  ],
  today: {
    requests: 47,
    prompt_tokens: 128400,
    completion_tokens: 36200,
    cached_tokens: 86000,
    cache_read_tokens: 74000,
    cache_creation_tokens: 12000,
    estimated_cost_usd: 0.52,
    known_requests: 47,
    unknown_requests: 0,
  },
  cache_hit_rate: 0.4848,
  range: 'today',
  known_requests: 1284,
  unknown_requests: 0,
  has_partial_estimates: false,
  known_requests_today: 47,
  unknown_requests_today: 0,
};

/** 文献调研会话的 session_summary 记忆 (get_session_summaries 专用; 含 1 条 failed 展示徽章) */
export const DEMO_SURVEY_SUMMARIES: Memory[] = [
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

export const DEMO_SCHEDULED_TASKS: ScheduledTask[] = [
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

export const DEMO_SKILL_RUN_OUTPUT = `# 2026-08-27 日报

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
