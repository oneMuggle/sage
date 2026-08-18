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
 */
export const AGENT_RUNTIME_MESSAGES: Record<string, string> = {
  max_iterations_exceeded: '任务复杂度超出当前迭代上限，可在 Agent 管理页调高"最大迭代次数"后重试',
  tool_budget_exceeded: '工具调用次数超出单轮预算，请拆分任务后重试',
  subagent_loop_failed: '子代理执行未完成，请重试或简化子任务',
  subagent_exhausted_iterations: '子代理未在迭代预算内收敛，请拆分任务后重试',
};

export function mapAgentErrorToText(code: string): string | null {
  if (typeof code !== 'string' || !code) return null;
  // hasOwnProperty 防御原型链：'constructor'/'toString' 不是合法错误码
  return Object.prototype.hasOwnProperty.call(AGENT_RUNTIME_MESSAGES, code)
    ? AGENT_RUNTIME_MESSAGES[code]
    : null;
}
