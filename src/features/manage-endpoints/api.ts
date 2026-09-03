import {
  DEMO_ENDPOINT_MODELS,
  type DiscoveredModel,
  type ModelCapability,
} from '../../entities/setting/types';
import { backendRequest } from '../../shared/api/backendRequest';
import { isDemoMode } from '../../shared/api/demoInterceptors';

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
 * 后端 LLM 代理 (backend/api/llm_proxy_routes.py) 在上游非 2xx / 网络故障 /
 * TLS 失败时透传一段稳定的 envelope, ``detail.type`` 标识错误种类, ``detail.message``
 * 是不泄露上游响应体的安全提示 (如 ``"Upstream returned HTTP 401."``)。
 *
 * Electron IPC 层 (electron/main.ts sage:backend-request) 把这种 envelope 当作非 2xx
 * raw body 抛出 Error, message 形如::
 *
 *     Backend request failed: 401 {"detail":{"type":"upstream_error","message":"Upstream returned HTTP 401."}}
 *
 * 直接把这段贴给前端既冗长又无法辨识。本函数从 message 里抽出 status + JSON detail,
 * 翻译成中文友好提示, 让 toast 不再粘贴整段 IPC 错误。
 *
 * 解析失败一律降级到 ``<原 message>``, 不抛错 — 任何 I/O 边界 helper 都应保持非抛。
 */
function _parseUpstreamError(err: unknown): string {
  const raw = err instanceof Error ? err.message : String(err);
  // 1. 抽 JSON detail 子串。message 形如
  //    ``Backend request failed: 401 {"detail":{...}}``, 用非贪婪 JSON 切片拿到 detail。
  const jsonMatch = raw.match(/\{\s*"detail"\s*:[^{}]*(?:\{[^{}]*\}[^{}]*)*\}/);
  let detailType: string | undefined;
  if (jsonMatch) {
    try {
      const parsed = JSON.parse(jsonMatch[0]) as { detail?: { type?: string; message?: string } };
      detailType = parsed.detail?.type;
    } catch {
      // JSON 损坏时静默降级 — 走 status 分支
    }
  }
  // 2. 抽 status code。兼容两种 message 形态:
  //    - IPC raw: ``Backend request failed: 401 <body>``
  //    - 测试 mock: ``HTTP 401: <body>``
  const statusMatch = raw.match(/(?:Backend request failed:|HTTP\s+)(\d{3})/i);
  const status = statusMatch ? Number(statusMatch[1]) : undefined;

  // 3. 按 detail.type 优先翻译 (类型稳定, 跨 status 都适用)
  if (detailType === 'upstream_unreachable') {
    return '上游服务不可达：请检查 Base URL 与网络连通性';
  }
  if (detailType === 'upstream_transport_error') {
    return '上游连接中断：请稍后重试';
  }
  if (detailType === 'tls_certificate_failed') {
    return '上游 TLS 证书校验失败：请检查 Base URL 与证书配置';
  }
  if (detailType === 'upstream_timeout') {
    return '上游请求超时';
  }
  if (detailType === 'request_body_too_large') {
    return '请求体过大';
  }
  if (detailType === 'response_body_too_large') {
    return '上游响应过大';
  }
  // 4. upstream_error + status: 给常见状态码定制提示, 其它落到通用模板
  if (detailType === 'upstream_error' && status !== undefined) {
    if (status === 401) return '上游返回 401：API Key 无效或已过期，请检查 endpoint 配置';
    if (status === 403) return '上游返回 403：权限不足，请检查 API Key 权限或账户状态';
    if (status === 404) return '上游返回 404：请检查 Base URL 是否正确（缺少 /v1 路径或地址拼错）';
    if (status === 429) return '上游返回 429：请求频率限制，请稍后重试';
    if (status >= 500 && status <= 599) {
      return `上游返回 ${status}：服务异常，请稍后重试`;
    }
    return `上游返回 ${status}：请检查 endpoint 配置`;
  }
  // 5. 已知 status 但无 detail.type (非 envelope 路径, 例如裸 fetch 失败或测试 mock)
  if (status !== undefined) {
    if (status === 401) return '上游返回 401：API Key 无效或已过期';
    if (status === 403) return '上游返回 403：权限不足';
    if (status === 404) return '上游返回 404：Base URL 路径错误';
    if (status === 429) return '上游返回 429：请求频率限制';
    if (status >= 500 && status <= 599) return `上游返回 ${status}：服务异常`;
  }
  // 6. 兜底 — 保留原 message, 与现有行为兼容
  return raw;
}

/**
 * Fetch available models from an OpenAI-compatible endpoint.
 *
 * 实际打到本机后端代理 ``${LLM_PROXY_BASE}/v1/models``;
 * 真实上游地址通过 ``X-LLM-Provider-Url`` 头传入,后端用 ``httpx`` 透传。
 * 这样浏览器永远只跟同源后端对话,绕开 CORS。
 */
export async function fetchModels(baseUrl: string, apiKey: string): Promise<DiscoveredModel[]> {
  if (isDemoMode()) return DEMO_ENDPOINT_MODELS.map((model) => ({ ...model }));
  const response = await backendRequest<OpenAIModelsResponse>({
    path: `${LLM_PROXY_BASE}/v1/models`,
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
    // 401/429/上游 envelope → _parseUpstreamError 统一翻译; 其它降级到原 message。
    return { success: false, message: _parseUpstreamError(error) };
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
  if (isDemoMode()) {
    return {
      success: true,
      message: `演示端点可用 · 发现 ${DEMO_ENDPOINT_MODELS.length} 个模型 · 未发送网络请求`,
      latency: 0,
      discoveredModels: DEMO_ENDPOINT_MODELS.map((model) => ({ ...model })),
    };
  }
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
    // fetchModels 阶段抛出的 error 含 backend upstream_error envelope, _parseUpstreamError
    // 会翻译成中文友好提示; 兜底时保留 raw message, 不抛错。
    return {
      success: false,
      message: `连接失败: ${_parseUpstreamError(error)}`,
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
