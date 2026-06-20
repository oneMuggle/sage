/**
 * Sage API - 工具函数
 * 包含输入安全处理、验证、重试逻辑和错误处理
 */

import type { LLMErrorResponse } from '../lib/errorMapping';

import type { ApiError } from './types';

// ==================== ApiException 类 ====================

export class ApiException extends Error {
  code: string;
  details: Record<string, unknown>;
  llmError?: LLMErrorResponse;

  constructor(error: ApiError) {
    super(error.message);
    this.name = 'ApiException';
    this.code = error.error;
    this.details = error.details || {};
    this.llmError = error.llmError;
  }
}

// ==================== 重试配置 ====================

interface RetryConfig {
  maxRetries: number; // 最大重试次数
  retryDelay: number; // 重试延迟（毫秒）
  backoffMultiplier: number; // 退避倍数
}

const defaultRetryConfig: RetryConfig = {
  maxRetries: 3,
  retryDelay: 1000,
  backoffMultiplier: 2,
};

// ==================== 输入安全处理 ====================

/**
 * 安全化用户输入，防止 XSS 攻击
 * @param input 用户输入字符串
 * @returns 安全化后的字符串
 */
export function sanitizeInput(input: string): string {
  if (typeof input !== 'string') {
    return '';
  }

  return input
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#x27;')
    .replace(/\//g, '&#x2F;');
}

/**
 * 验证会话ID格式
 * @param sessionId 会话ID
 * @returns 是否有效
 */
export function isValidSessionId(sessionId: string): boolean {
  // UUID 格式验证
  const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  return uuidRegex.test(sessionId);
}

// ==================== 重试逻辑 ====================

export async function withRetry<T>(
  operation: () => Promise<T>,
  config: Partial<RetryConfig> = {},
): Promise<T> {
  const { maxRetries, retryDelay, backoffMultiplier } = {
    ...defaultRetryConfig,
    ...config,
  };

  let lastError: Error | null = null;
  let currentDelay = retryDelay;

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await operation();
    } catch (error) {
      lastError = error as Error;

      // 如果还有重试机会
      if (attempt < maxRetries) {
        console.warn(`请求失败，第 ${attempt + 1} 次重试，${currentDelay}ms 后...`);
        await new Promise((resolve) => setTimeout(resolve, currentDelay));
        currentDelay *= backoffMultiplier;
      }
    }
  }

  // 所有重试都失败了
  throw lastError;
}

// ==================== 错误处理 ====================

export function handleApiError(error: unknown): ApiException {
  if (error instanceof ApiException) {
    return error;
  }

  // 尝试解析错误响应
  if (error && typeof error === 'object' && 'error' in error) {
    const e = error as { error: unknown; message?: string };
    // 如果内层 error 字段是 LLMErrorResponse（带 type），保留完整对象
    if (e.error && typeof e.error === 'object' && 'type' in e.error) {
      const llmError = e.error as LLMErrorResponse;
      return new ApiException({
        error: llmError.type,
        message: e.message ?? llmError.message,
        llmError,
      });
    }
    return new ApiException({
      error: e.error as string,
      message: e.message as string,
    });
  }

  // 包装未知错误
  return new ApiException({
    error: 'UNKNOWN_ERROR',
    message: error instanceof Error ? error.message : '未知错误',
    details: { originalError: String(error) },
  });
}
