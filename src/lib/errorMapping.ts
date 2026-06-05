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
  | 'unknown'

export interface LLMErrorResponse {
  type: LLMErrorTypeFE
  message: string
  status_code: number | null
  retry_after: number | null
}

const STATIC_MESSAGES: Record<LLMErrorTypeFE, string> = {
  auth_failed: 'API Key 无效或过期，请在设置中检查',
  rate_limited: '请求过于频繁，请稍后再试',
  server_error: 'LLM 服务端错误，请稍后再试',
  network_error: '无法连接到 LLM 服务，请检查网络',
  timeout: '请求超时，请重试',
  parsing_error: '原始消息',  // 解析错误用原始消息
  unknown: '未知错误',
}

export function mapLLMErrorToText(err: LLMErrorResponse): string {
  const base = STATIC_MESSAGES[err.type]
  if (err.type === 'rate_limited' && err.retry_after) {
    return `${base}（建议 ${err.retry_after} 秒后重试）`
  }
  return base ?? err.message
}
