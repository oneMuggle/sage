/**
 * LLM 错误类型到中文化提示的映射
 */

export type LLMErrorTypeFE =
  | 'auth_failed'
  | 'rate_limited'
  | 'server_error'
  | 'network_error'
  | 'timeout'
  | 'parsing_error'
  | 'unknown';

export interface LLMErrorResponse {
  type: LLMErrorTypeFE;
  message: string;
  status_code: number | null;
  retry_after: number | null;
}

const STATIC_MESSAGES: Record<LLMErrorTypeFE, string> = {
  auth_failed: 'API Key 无效或过期，请在设置中检查',
  rate_limited: '请求过于频繁，请稍后再试',
  server_error: 'LLM 服务端错误，请稍后再试',
  network_error: '无法连接到 LLM 服务，请检查网络',
  timeout: '请求超时，请重试',
  parsing_error: '原始消息', // 解析错误用原始消息
  unknown: '未知错误',
};

export function mapLLMErrorToText(err: LLMErrorResponse): string {
  const base = STATIC_MESSAGES[err.type];
  if (err.type === 'rate_limited' && err.retry_after) {
    return `${base}（建议 ${err.retry_after} 秒后重试）`;
  }
  return base ?? err.message;
}

/**
 * Agent 运行时错误码到中文化提示的映射。
 *
 * 与 LLM transport 错误不同：这些是 agent loop 自身的失败信号（迭代超限、
 * 工具预算耗尽、子代理失败等），由后端 ``agent.run_loop`` / ``agent_tool``
 * 抛出，前端 ``chatApi`` 路径会原样冒泡到 ``useChat.handleError``。
 *
 * 注意：必须是独立表而非 ``STATIC_MESSAGES`` 的扩展——
 * ``STATIC_MESSAGES`` 的键受 ``LLMErrorTypeFE`` 字面量联合约束，
 * 加入非 LLM 码会破坏 ``mapLLMErrorToText`` 的类型契约。
 *
 * ``{limit}`` 占位符由 ``mapAgentErrorToText`` 在解析出上限值时替换成
 * "数值 + 单位"；裸码（无上限装饰）时该占位符会被移除。
 */
export const AGENT_RUNTIME_MESSAGES: Record<string, string> = {
  // {subject} / {limit} / {source} / {hint} 由 buildIterationLimitMessage 渲染：
  // 有 agent / source 上下文时给出"哪个 agent、哪个上限来源、去哪调"，
  // 裸码时回落成通用文案。
  max_iterations_exceeded: '{subject}达到迭代上限{limit}{source}。{hint}',
  tool_budget_exceeded:
    '工具调用次数超出单轮预算{limit}，可在「设置 → 编排 → 工具调用预算」调高或拆分任务后重试',
  prompt_blocked_by_hook: '消息被用户自定义钩子拦截（可在 设置 → 通用 → 钩子 管理）',
  spend_limit_exceeded:
    '已达到今日花费限额{limit}，为控制成本本次请求未发送（可在 设置 → 通用 调整）',
  subagent_loop_failed: '子代理执行未完成，请重试或简化子任务',
  subagent_exhausted_iterations:
    '子代理未在迭代预算内收敛{limit}，可在「设置 → 编排 → 子代理迭代上限」调高或拆分任务后重试',
  // 2026-10-22: 整轮任务 wall-clock 预算耗尽。显式排除网络/端点语义，
  // 否则用户会误以为是接口断了而去查端点连通性。
  llm_total_timeout:
    '整轮任务总耗时超出上限{limit}（含 LLM 调用 + 工具执行 + 子代理的累计耗时），与网络或端点连通性无关，可在「设置 → 基础 → LLM 任务上限」调高后重试',
};

/**
 * agent profile id → 中文显示名。
 *
 * 后端下发的 agent=<id> 是内部 profile id（如 `ppt-maker`），直接透给用户
 * 不友好；未收录的 id 回落成原 id，保证信息不丢。
 */
const AGENT_DISPLAY_NAMES: Record<string, string> = {
  primary: '主助手',
  researcher: '研究员',
  coder: '编码助手',
  writer: '写作助手',
  reviewer: '审查助手',
  memory_manager: '记忆助手',
  'ppt-maker': 'PPT 助手',
};

/** 上限来源层级 → 中文标签（与后端 agent.py 的 _limit_source 对齐）。 */
const ITERATION_LIMIT_SOURCE_LABELS: Record<string, string> = {
  explicit: '调用方指定',
  'orch.global': '编排全局设置',
  profile: 'Agent 默认配置',
  default: '系统默认值',
};

/** 上限来源层级 → 用户该去哪调。 */
const ITERATION_LIMIT_HINTS: Record<string, string> = {
  'orch.global':
    '可在「设置 → 编排 → Agent 迭代次数上限」调高后重试，或拆分任务减少往返。',
  profile:
    '可在 Agent 编辑面板调整该 Agent 的最大迭代次数后重试，或拆分任务减少往返。',
  explicit: '该上限由本次调用指定，可拆分任务减少往返后重试。',
  default:
    '可在「设置 → 编排 → Agent 迭代次数上限」调高后重试，或拆分任务减少往返。',
};

const DEFAULT_ITERATION_HINT =
  '可在「设置 → 编排 → Agent 迭代次数上限」调高后重试，或拆分任务减少往返。';


/**
 * 上限值的中文单位。按错误码区分，裸码路径不查此表。
 */
const AGENT_RUNTIME_LIMIT_UNITS: Record<string, string> = {
  max_iterations_exceeded: '次',
  tool_budget_exceeded: '次',
  subagent_exhausted_iterations: '次',
  spend_limit_exceeded: 'USD',
  llm_total_timeout: '秒',
};

/**
 * 后端下发的错误串格式：``<code> (limit=<数值>[, agent=<id>[, source=<src>]])``。
 *
 * 后缀追加在末尾而非替换错误码，保证 ``<code>`` 仍是前缀，
 * 任何按前缀/startsWith 判断的消费方都保持兼容。
 *
 * ``agent=`` / ``source=`` 是 2026-10-29 新增的可选字段，用于告诉用户
 * "是哪个 agent 打的哪个上限"。旧格式（只有 limit=）继续可解析。
 */
const AGENT_ERROR_DECORATION_RE = /^([a-z][a-z0-9_]*)\s*\(([^()]*)\)$/;

export interface AgentErrorLimit {
  /** 不含上限装饰的错误码 */
  code: string;
  /** 上限数值（程序判断用） */
  value: number;
  /** 上限原始文本（保留 "50.00" 的精度，避免金额被截成 50） */
  text: string;
  /** 触发上限的 agent（后端 profile id / agent_id），旧格式没有 */
  agent?: string;
  /** 上限来源层级：explicit / orch.global / profile / default，旧格式没有 */
  source?: string;
}

/**
 * 解析 ``"<code> (limit=N)"`` 形式的上限装饰。
 *
 * 非该格式（含裸码、中文文案、空串）返回 null，调用方走原有的
 * "整串当作错误码" 分支。
 */
export function parseAgentErrorLimit(raw: string): AgentErrorLimit | null {
  if (typeof raw !== 'string' || !raw) return null;
  const matched = AGENT_ERROR_DECORATION_RE.exec(raw);
  if (!matched) return null;

  // 用 Map 而非普通对象：装饰段来自网络输入，避免 __proto__ 之类的键污染原型链。
  const fields = new Map<string, string>();
  for (const part of matched[2].split(',')) {
    const eq = part.indexOf('=');
    if (eq <= 0) continue;
    const key = part.slice(0, eq).trim();
    const value = part.slice(eq + 1).trim();
    if (!key || !value) continue;
    fields.set(key, value);
  }

  const limitText = fields.get('limit');
  if (limitText === undefined || !/^\d+(?:\.\d+)?$/.test(limitText)) return null;

  const parsed: AgentErrorLimit = {
    code: matched[1],
    value: Number(limitText),
    text: limitText,
  };
  const agent = fields.get('agent');
  if (agent) parsed.agent = agent;
  const source = fields.get('source');
  if (source) parsed.source = source;
  return parsed;
}

/**
 * 迭代上限错误的专属文案。
 *
 * 与其他错误码不同，这里要同时回答三件事：哪个 agent、哪个上限来源、
 * 去哪里调。裸码（无 agent / source）时回落成通用文案。
 */
function buildIterationLimitMessage(parsed: AgentErrorLimit | null): string {
  const template = AGENT_RUNTIME_MESSAGES.max_iterations_exceeded;
  const agentId = parsed?.agent ?? '';
  const agentName = agentId ? (AGENT_DISPLAY_NAMES[agentId] ?? agentId) : '';
  const source = parsed?.source ?? '';

  const subject = agentName ? `「${agentName}」` : '本次任务';
  const unit = AGENT_RUNTIME_LIMIT_UNITS.max_iterations_exceeded;
  const limit = parsed ? ` ${parsed.text} ${unit}` : '';
  const sourceLabel = ITERATION_LIMIT_SOURCE_LABELS[source];
  const sourcePart = sourceLabel ? `（上限来源：${sourceLabel}）` : '';
  const hint = ITERATION_LIMIT_HINTS[source] ?? DEFAULT_ITERATION_HINT;

  return template
    .replace('{subject}', subject)
    .replace('{limit}', limit)
    .replace('{source}', sourcePart)
    .replace('{hint}', hint);
}

/**
 * 把 agent 运行时错误码/错误串映射为中文化提示。
 *
 * 入参既可以是裸码（``"max_iterations_exceeded"``），也可以是带上限装饰的
 * 完整错误串（``"max_iterations_exceeded (limit=25)"``）。后一种会渲染出
 * 具体上限值，方便用户知道该把设置调到多少。
 *
 * 未知错误码返回 null，由调用方回退到原始文本。
 */
export function mapAgentErrorToText(code: string): string | null {
  if (typeof code !== 'string' || !code) return null;

  const parsed = parseAgentErrorLimit(code);
  const bare = parsed ? parsed.code : code;

  // hasOwnProperty 防御原型链：'constructor'/'toString' 不是合法错误码
  if (!Object.prototype.hasOwnProperty.call(AGENT_RUNTIME_MESSAGES, bare)) return null;

  if (bare === 'max_iterations_exceeded') return buildIterationLimitMessage(parsed);

  const template = AGENT_RUNTIME_MESSAGES[bare];

  if (!parsed) {
    // 裸码：模板含 {limit} 时不能把占位符漏给用户
    return template.replace(/\{limit\}/g, '');
  }

  const unit = Object.prototype.hasOwnProperty.call(AGENT_RUNTIME_LIMIT_UNITS, bare)
    ? AGENT_RUNTIME_LIMIT_UNITS[bare]
    : '';
  const rendered = unit ? `${parsed.text} ${unit}` : parsed.text;

  if (!template.includes('{limit}')) {
    // 模板未声明 {limit}：仍把上限值附在末尾，避免信息丢失
    return `${template}（上限 ${rendered}）`;
  }
  return template.replace(/\{limit\}/g, rendered);
}

export function formatLLMErrorSummary(err: LLMErrorResponse): string {
  return `${err.type} · status=${err.status_code ?? 'none'} · retry=${err.retry_after ?? 'none'} · ${mapLLMErrorToText(err)}`;
}

export function formatLLMErrorJson(err: LLMErrorResponse): string {
  return JSON.stringify(
    {
      type: err.type,
      statusCode: err.status_code,
      retryAfter: err.retry_after,
      mappedText: mapLLMErrorToText(err),
    },
    null,
    2,
  );
}

export function auditErrorMappingGovernance(): string {
  return JSON.stringify(
    {
      schema: 'sage.shared.lib.error_mapping.governance.v1',
      phase: 'P178',
      runtimeErrorCodes: Object.keys(AGENT_RUNTIME_MESSAGES),
      sampleLlmSummary: formatLLMErrorSummary({
        type: 'rate_limited',
        message: 'Too many requests',
        status_code: 429,
        retry_after: 5,
      }),
    },
    null,
    2,
  );
}
