import type { DiscoveredModel, ModelCapability } from '../../entities/setting/types';

interface OpenAIModelInfo {
  id: string;
  object: string;
  created?: number;
  owned_by?: string;
}

interface OpenAIModelsResponse {
  object: string;
  data: OpenAIModelInfo[];
}

export interface ConnectionTestResult {
  success: boolean;
  message: string;
  latency: number;
  /** Models discovered during the test (present on success) */
  discoveredModels?: DiscoveredModel[];
}

/**
 * 所有浏览器到 LLM 的请求统一走本机后端代理,避免 CORS。
 * 见 ``docs/technical/21-llm-proxy.md`` 与 ``backend/api/llm_proxy_routes.py``。
 * 可通过 ``VITE_LLM_PROXY_BASE`` 覆盖,默认 ``http://localhost:8765/api/v1/llm``。
 */
const LLM_PROXY_BASE: string =
  (import.meta.env.VITE_LLM_PROXY_BASE as string | undefined) ?? 'http://localhost:8765/api/v1/llm';

/** 构造代理请求头:Authorization + X-LLM-Provider-Url。 */
function proxyHeaders(providerUrl: string, apiKey: string): HeadersInit {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-LLM-Provider-Url': providerUrl,
  };
  // Ollama 等本地服务默认无鉴权,空 apiKey 不要发「Bearer 」(避免上游 log 噪音)
  if (apiKey) {
    headers.Authorization = `Bearer ${apiKey}`;
  }
  return headers;
}

/**
 * Fetch available models from an OpenAI-compatible endpoint.
 *
 * 实际打到本机后端代理 ``${LLM_PROXY_BASE}/v1/models``;
 * 真实上游地址通过 ``X-LLM-Provider-Url`` 头传入,后端用 ``httpx`` 透传。
 * 这样浏览器永远只跟同源后端对话,绕开 CORS。
 */
export async function fetchModels(baseUrl: string, apiKey: string): Promise<DiscoveredModel[]> {
  const response = await fetch(`${LLM_PROXY_BASE}/v1/models`, {
    method: 'GET',
    headers: proxyHeaders(baseUrl, apiKey),
  });
  const data = response;
  return data.data.map((m) => ({
    id: m.id,
    capabilities: inferCapabilities(m.id),
    endpointId: '',
  }));
}

/**
 * Test a chat completion call to verify the actual chat endpoint works.
 *
 * 同 ``fetchModels`` — 走本机后端代理,真实上游通过 ``X-LLM-Provider-Url`` 头传入。
 */
async function testChatCompletion(
  baseUrl: string,
  apiKey: string,
  model: string,
): Promise<{ success: boolean; message: string }> {
  try {
    const response = await backendRequest<{ choices?: unknown[] }>({
      path: `${LLM_PROXY_BASE}/v1/chat/completions`,
      method: 'POST',
      headers: proxyHeaders(baseUrl, apiKey),
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
    const message = error instanceof Error ? error.message : String(error);
    const statusMatch = message.match(/(?:HTTP|Backend request failed:)\s*(\d{3})/i);
    const status = statusMatch ? Number(statusMatch[1]) : undefined;
    if (status === 401) return { success: false, message: 'API Key 无效' };
    if (status === 429) return { success: false, message: '请求频率限制' };
    return { success: false, message };
  }
}

/**
 * Test connectivity to an OpenAI-compatible endpoint.
 * Tests both /models discovery and /chat/completions.
 */
export async function testEndpointConnection(
  baseUrl: string,
  apiKey: string,
  chatModel?: string,
): Promise<ConnectionTestResult> {
  const start = Date.now();
  try {
    // Step 1: Test /models endpoint
    const models = await fetchModels(baseUrl, apiKey);
    const modelDiscovery = `发现 ${models.length} 个模型`;

    // Step 2: 选定 chat 测试模型
    // 优先用调用方传入的 chatModel, 但仅当它属于被测端点 (出现在 /v1/models 列表) 时;
    // 否则回退到被测端点第一个非 embedding 模型。避免「用端点 A 的全局模型测端点 B」
    // 触发上游网关 503 model_not_found (如 AgnesAI 按 token 分组路由模型), 也避免
    // 拿纯 embedding 模型打 /chat/completions 触发假失败。
    let chatTestModel = chatModel;
    if (!chatTestModel || !models.some((m) => m.id === chatTestModel)) {
      chatTestModel = models.find((m) => !isEmbeddingModel(m.id))?.id;
    }

    // Step 3: Test /chat/completions if a chat model is available
    if (chatTestModel) {
      const chatResult = await testChatCompletion(baseUrl, apiKey, chatTestModel);
      if (!chatResult.success) {
        return {
          success: false,
          message: `${modelDiscovery}，但聊天端点异常: ${chatResult.message}`,
          latency: Date.now() - start,
          discoveredModels: models,
        };
      }
      return {
        success: true,
        message: `连接成功 · ${modelDiscovery} · ${chatResult.message}`,
        latency: Date.now() - start,
        discoveredModels: models,
      };
    }

    return {
      success: true,
      message: `连接成功，${modelDiscovery}`,
      latency: Date.now() - start,
      discoveredModels: models,
    };
  } catch (error) {
    return {
      success: false,
      message: `连接失败: ${error instanceof Error ? error.message : String(error)}`,
      latency: Date.now() - start,
    };
  }
}

/**
 * 判断模型 id 是否为 embedding 模型 (不适合作 chat 连通性测试)。
 *
 * 注意: ``inferCapabilities`` 无条件给所有模型标 ``'chat'``, 所以 fallback 选
 * 测试模型时不能依赖 capabilities 过滤, 需单独按 id 排除 embedding 模型, 避免
 * 拿纯 embedding 模型打 ``/chat/completions`` 触发假失败。
 */
function isEmbeddingModel(modelId: string): boolean {
  const lower = modelId.toLowerCase();
  return lower.includes('embed') || lower.includes('text-embedding') || lower.includes('vector');
}

/**
 * Infer model capabilities from the model ID string.
 */
function inferCapabilities(modelId: string): ModelCapability[] {
  const lower = modelId.toLowerCase();
  const caps: ModelCapability[] = ['chat'];

  if (
    lower.includes('vision') ||
    lower.includes('gpt-4o') ||
    lower.includes('gemini') ||
    lower.includes('claude-3') ||
    lower.includes('image')
  ) {
    caps.push('vision');
  }
  if (lower.includes('embed') || lower.includes('text-embedding') || lower.includes('vector')) {
    caps.push('embedding');
  }

  return caps;
}
