import { describe, it, expect } from 'vitest'
import { ApiException, type ApiError } from '../api'
import { mapLLMErrorToText } from '../errorMapping'

/**
 * 复现 handleApiError 的核心逻辑，避免触发 import { invoke } 的副作用
 * 这是后端 /chat 端点返回的 JSON 形状。
 */
interface BackendErrorEnvelope {
  error: unknown
  message?: string | null
  message_detail?: unknown
  session?: unknown
}

function wrapLikeHandleApiError(raw: BackendErrorEnvelope): ApiError {
  if (raw.error && typeof raw.error === 'object' && 'type' in raw.error) {
    const llmError = raw.error as {
      type: string
      message: string
      status_code: number | null
      retry_after: number | null
    }
    return {
      error: llmError.type,
      message: (raw.message as string | null | undefined) ?? llmError.message,
      llmError: llmError as never,
    }
  }
  return { error: raw.error as string, message: (raw.message as string) ?? '' }
}

describe('ApiException preserves LLMErrorResponse', () => {
  it('preserves structured LLMErrorResponse when wrapping backend error envelope', () => {
    const backendResponse: BackendErrorEnvelope = {
      error: {
        type: 'auth_failed',
        message: 'API Key 无效',
        status_code: 401,
        retry_after: null,
      },
      message: '服务内部错误', // 顶层 message 通常是泛化的
      message_detail: null,
      session: null,
    }

    const err = wrapLikeHandleApiError(backendResponse)
    const ex = new ApiException(err)

    expect(ex.llmError).toBeDefined()
    expect(ex.llmError?.type).toBe('auth_failed')
    expect(ex.llmError?.status_code).toBe(401)
    expect(ex.llmError?.message).toBe('API Key 无效')
  })

  it('useChat catch block can call mapLLMErrorToText with the preserved llmError', () => {
    const ex = new ApiException({
      error: 'rate_limited',
      message: 'Rate limited',
      llmError: {
        type: 'rate_limited',
        message: 'Too many',
        status_code: 429,
        retry_after: 30,
      },
    })

    // 模拟 useChat catch 中的核心逻辑
    if (!(ex instanceof ApiException) || !ex.llmError) {
      throw new Error('expected ApiException with llmError')
    }
    const text = mapLLMErrorToText(ex.llmError)

    expect(text).toContain('30 秒后重试')
  })

  it('falls back gracefully when error envelope is not LLMErrorResponse-shaped', () => {
    const raw: BackendErrorEnvelope = { error: 'NETWORK_DOWN', message: 'no internet' }
    const err = wrapLikeHandleApiError(raw)
    const ex = new ApiException(err)

    expect(ex.llmError).toBeUndefined()
    expect(ex.code).toBe('NETWORK_DOWN')
    expect(ex.message).toBe('no internet')
  })
})
