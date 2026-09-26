/**
 * Provider 注册表（A2 前端侧）。
 *
 * 把各 LLM 协议的差异（模型发现路径、对话测试路径、认证头格式、
 * 响应解析逻辑）封装为 ``ProviderDefinition``，替代 ``api.ts`` 和
 * ``EndpointsTab.tsx`` 中的 if/else 硬编码。
 *
 * 设计要点
 *
 * - **纯前端注册表**：运行时从内存读取，不持久化。
 * - **工厂模式**：每个 provider 定义包含 ``fetchModels`` 和 ``testChat``
 *   两个异步方法，供 ``api.ts`` 调用。
 * - **可扩展**：新增 provider 只需 ``registerProvider()``，不修改现有代码。
 */

import type { DiscoveredModel, EndpointProtocol, ModelCapability } from '../setting/types';

// ============================================================================
// ProviderDefinition 接口
// ============================================================================

export interface ProviderDefinition {
  /** 协议标识（与 EndpointProtocol 对齐） */
  id: EndpointProtocol;
  /** 前端下拉菜单显示名称 */
  label: string;
  /** 是否需要 API key */
  needsApiKey: boolean;
  /** 默认 base URL（占位符用） */
  defaultBaseUrl: string;
  /** 默认端口（用于 URL 拼接提示） */
  defaultPort?: number;

  /**
   * 模型发现：调用后端代理拉取可用模型列表。
   *
   * @param baseUrl 用户配置的 API 基础 URL
   * @param apiKey  API key（可能为空串）
   * @param backendRequest 后端代理请求函数（避免本模块直接依赖 api.ts）
   */
  fetchModels: (
    baseUrl: string,
    apiKey: string,
    backendRequest: BackendRequestFn,
  ) => Promise<DiscoveredModel[]>;

  /**
   * 对话端点连通测试：发一个最小 chat 请求验证端点可用。
   *
   * @param baseUrl 用户配置的 API 基础 URL
   * @param apiKey  API key
   * @param model   用于测试的模型名
   * @param backendRequest 后端代理请求函数
   */
  testChat: (
    baseUrl: string,
    apiKey: string,
    model: string,
    backendRequest: BackendRequestFn,
  ) => Promise<{ success: boolean; message: string }>;
}

/**
 * 后端代理请求函数签名（从 api.ts 注入，避免循环依赖）。
 */
export type BackendRequestFn = <T>(options: {
  path: string;
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  headers?: Record<string, string>;
  body?: unknown;
  timeoutMs?: number;
}) => Promise<T>;

// ============================================================================
// 注册表实现
// ============================================================================

const _registry = new Map<EndpointProtocol, ProviderDefinition>();

export function registerProvider(def: ProviderDefinition): void {
  _registry.set(def.id, def);
}

export function getProviderDefinition(protocol: EndpointProtocol): ProviderDefinition | undefined {
  return _registry.get(protocol);
}

export function listProviders(): ProviderDefinition[] {
  return Array.from(_registry.values());
}

/**
 * 下拉菜单选项（按注册顺序）。
 */
export function getProtocolOptions(): ReadonlyArray<{
  value: EndpointProtocol;
  label: string;
}> {
  return listProviders().map((p) => ({ value: p.id, label: p.label }));
}

// ============================================================================
// LLM_PROXY_BASE 常量（避免循环依赖 api.ts）
// ============================================================================

const LLM_PROXY_BASE = '/api/v1/llm-proxy';

// ============================================================================
// 辅助函数
// ============================================================================

/**
 * 推断模型能力（与 api.ts 现有 inferCapabilities 对齐）。
 */
function inferCapabilities(id: string): ModelCapability[] {
  const lower = id.toLowerCase();
  const caps: ModelCapability[] = ['chat'];
  if (lower.includes('embedding')) {
    return ['embedding'];
  }
  if (lower.includes('vision') || lower.includes('4o')) {
    caps.push('vision');
  }
  return caps;
}

// ============================================================================
// 内置 Provider 定义
// ============================================================================

// --- OpenAI 兼容 ---

registerProvider({
  id: 'openai-compatible',
  label: 'OpenAI 兼容 (LM Studio / OpenAI / 其他 /v1/*)',
  needsApiKey: true,
  defaultBaseUrl: 'https://api.openai.com/v1',
  fetchModels: async (baseUrl, apiKey, backendRequest) => {
    const base = baseUrl.replace(/\/+$/, '');
    const response = await backendRequest<{ data?: Array<{ id?: string }> }>({
      path: `${LLM_PROXY_BASE}/v1/models`,
      method: 'GET',
      headers: {
        'X-LLM-Provider-Url': base,
        ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}),
      },
    });
    return (response.data ?? [])
      .map((m) => String(m.id ?? ''))
      .filter(Boolean)
      .map((id) => ({
        id,
        capabilities: inferCapabilities(id),
        endpointId: '',
      }));
  },
  testChat: async (baseUrl, apiKey, model, backendRequest) => {
    try {
      const response = await backendRequest<{ choices?: unknown[] }>({
        path: `${LLM_PROXY_BASE}/v1/chat/completions`,
        method: 'POST',
        headers: {
          'X-LLM-Provider-Url': baseUrl.replace(/\/+$/, ''),
          ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}),
        },
        body: {
          model,
          messages: [{ role: 'user', content: 'Hi' }],
          max_tokens: 10,
        },
        timeoutMs: 15_000,
      });
      if (!response || typeof response !== 'object' || !Array.isArray(response.choices)) {
        return { success: false, message: '聊天端点异常' };
      }
      return { success: true, message: '聊天端点正常' };
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        return { success: false, message: '请求超时 (15s)' };
      }
      return { success: false, message: String(error) };
    }
  },
});

// --- Anthropic ---

registerProvider({
  id: 'anthropic',
  label: 'Anthropic Messages',
  needsApiKey: true,
  defaultBaseUrl: 'https://api.anthropic.com',
  fetchModels: async (baseUrl, apiKey, backendRequest) => {
    const base = baseUrl.replace(/\/+$/, '');
    const response = await backendRequest<{ data?: Array<{ id?: string }> }>({
      path: `${LLM_PROXY_BASE}/v1/models`,
      method: 'GET',
      headers: {
        'X-LLM-Provider-Url': base,
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01',
      },
    });
    return (response.data ?? [])
      .map((m) => String(m.id ?? ''))
      .filter(Boolean)
      .map((id) => ({
        id,
        capabilities: inferCapabilities(id),
        endpointId: '',
      }));
  },
  testChat: async (baseUrl, apiKey, model, backendRequest) => {
    try {
      const response = await backendRequest<{ content?: unknown[] }>({
        path: `${LLM_PROXY_BASE}/v1/messages`,
        method: 'POST',
        headers: {
          'X-LLM-Provider-Url': baseUrl.replace(/\/+$/, ''),
          'x-api-key': apiKey,
          'anthropic-version': '2023-06-01',
        },
        body: {
          model,
          max_tokens: 10,
          messages: [{ role: 'user', content: 'Hi' }],
        },
        timeoutMs: 15_000,
      });
      if (!response || typeof response !== 'object' || !Array.isArray(response.content)) {
        return { success: false, message: '聊天端点异常' };
      }
      return { success: true, message: '聊天端点正常' };
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        return { success: false, message: '请求超时 (15s)' };
      }
      return { success: false, message: String(error) };
    }
  },
});

// --- Gemini ---

registerProvider({
  id: 'gemini',
  label: 'Google Gemini',
  needsApiKey: true,
  defaultBaseUrl: 'https://generativelanguage.googleapis.com/v1beta',
  fetchModels: async (baseUrl, apiKey, backendRequest) => {
    const base = baseUrl.replace(/\/+$/, '');
    const response = await backendRequest<{ models?: Array<{ name?: string }> }>({
      path: `${LLM_PROXY_BASE}/v1beta/models`,
      method: 'GET',
      headers: {
        'X-LLM-Provider-Url': base,
        'x-goog-api-key': apiKey,
      },
    });
    return (response.models ?? [])
      .map((m) => String(m.name ?? '').replace(/^models\//, ''))
      .filter(Boolean)
      .map((id) => ({
        id,
        capabilities: inferCapabilities(id),
        endpointId: '',
      }));
  },
  testChat: async (baseUrl, apiKey, model, backendRequest) => {
    try {
      const response = await backendRequest<{ candidates?: unknown[] }>({
        path: `${LLM_PROXY_BASE}/v1beta/models/${model}:generateContent`,
        method: 'POST',
        headers: {
          'X-LLM-Provider-Url': baseUrl.replace(/\/+$/, ''),
          'x-goog-api-key': apiKey,
        },
        body: {
          contents: [{ role: 'user', parts: [{ text: 'Hi' }] }],
          generationConfig: { maxOutputTokens: 10 },
        },
        timeoutMs: 15_000,
      });
      if (!response || typeof response !== 'object' || !Array.isArray(response.candidates)) {
        return { success: false, message: '聊天端点异常' };
      }
      return { success: true, message: '聊天端点正常' };
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        return { success: false, message: '请求超时 (15s)' };
      }
      return { success: false, message: String(error) };
    }
  },
});

// --- Ollama ---

registerProvider({
  id: 'ollama',
  label: 'Ollama 原生 (/api/chat)',
  needsApiKey: false,
  defaultBaseUrl: 'http://localhost:11434',
  defaultPort: 11434,
  fetchModels: async (baseUrl, _apiKey, backendRequest) => {
    const base = baseUrl.replace(/\/+$/, '');
    const response = await backendRequest<{ models?: Array<{ name?: string }> }>({
      path: `${LLM_PROXY_BASE}/api/tags`,
      method: 'GET',
      headers: { 'X-LLM-Provider-Url': base },
    });
    return (response.models ?? [])
      .map((m) => String(m.name ?? ''))
      .filter(Boolean)
      .map((id) => ({
        id,
        capabilities: inferCapabilities(id),
        endpointId: '',
      }));
  },
  testChat: async (baseUrl, _apiKey, model, backendRequest) => {
    try {
      const response = await backendRequest<{ message?: unknown }>({
        path: `${LLM_PROXY_BASE}/api/chat`,
        method: 'POST',
        headers: { 'X-LLM-Provider-Url': baseUrl.replace(/\/+$/, '') },
        body: {
          model,
          messages: [{ role: 'user', content: 'Hi' }],
          stream: false,
        },
        timeoutMs: 15_000,
      });
      if (!response || typeof response !== 'object' || !response.message) {
        return { success: false, message: '聊天端点异常' };
      }
      return { success: true, message: '聊天端点正常' };
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        return { success: false, message: '请求超时 (15s)' };
      }
      return { success: false, message: String(error) };
    }
  },
});
