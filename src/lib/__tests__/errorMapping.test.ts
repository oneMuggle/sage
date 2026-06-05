import { describe, it, expect } from 'vitest'

import { mapLLMErrorToText, type LLMErrorResponse, type LLMErrorTypeFE } from '../errorMapping'

describe('mapLLMErrorToText', () => {
  it('maps auth_failed to Chinese hint', () => {
    const err: LLMErrorResponse = { type: 'auth_failed', message: 'x', status_code: 401, retry_after: null }
    expect(mapLLMErrorToText(err)).toBe('API Key 无效或过期，请在设置中检查')
  })

  it('maps rate_limited with retry_after', () => {
    const err: LLMErrorResponse = { type: 'rate_limited', message: 'x', status_code: 429, retry_after: 60 }
    expect(mapLLMErrorToText(err)).toContain('60 秒后重试')
  })

  it('maps network_error', () => {
    const err: LLMErrorResponse = { type: 'network_error', message: 'x', status_code: null, retry_after: null }
    expect(mapLLMErrorToText(err)).toBe('无法连接到 LLM 服务，请检查网络')
  })

  it('uses original message for parsing_error', () => {
    const err: LLMErrorResponse = { type: 'parsing_error', message: '原始消息', status_code: null, retry_after: null }
    expect(mapLLMErrorToText(err)).toBe('原始消息')
  })

  it('returns unknown fallback for truly unknown type', () => {
    const err = { type: 'something_new' as LLMErrorTypeFE, message: 'fallback', status_code: null, retry_after: null }
    expect(mapLLMErrorToText(err)).toBe('fallback')
  })
})
