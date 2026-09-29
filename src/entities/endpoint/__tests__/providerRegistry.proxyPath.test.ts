/**
 * providerRegistry 代理路径护栏。
 *
 * 回归背景：``LLM_PROXY_BASE`` 曾误写为 ``/api/v1/llm-proxy``，而后端只挂载了
 * ``/api/v1/llm/{path:path}``（见 ``backend/main.py`` 的 ``include_router(
 * llm_proxy_router, prefix="/api/v1")``）。后果有二：
 *   1. 请求打到不存在的路由 —— 端点「测试连接」失败；
 *   2. 该路径不落在 ``local_auth.is_local_auth_valid`` 的 LLM 豁免前缀内，
 *      provider 的 API key 被当成本地 capability 比对 —— 恒 401
 *      「本地授权凭据无效或缺失」。
 *
 * 该文件此前零测试覆盖，是这处回归逃逸的直接原因。此处按协议锁定请求路径，
 * 使任一 provider 写错 base 都立即失败。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { getProviderDefinition, type BackendRequestFn } from '../providerRegistry';

/** 后端实际注册的 LLM 代理前缀 —— 与 backend/main.py 保持一致。 */
const BACKEND_LLM_PROXY_PREFIX = '/api/v1/llm';

/** 绝不应出现的路径前缀（曾经的错误常量）。 */
const FORBIDDEN_PREFIX = '/api/v1/llm-proxy';

type RelayCall = { path: string; headers: Record<string, string> };

const relayCalls: RelayCall[] = [];

/** 记录每个 provider 实际发出的 path，响应体保持各协议期望的形状。 */
function installRelayStub(): BackendRequestFn {
  relayCalls.length = 0;
  return vi.fn(async (request: { path: string; headers?: Record<string, string> }) => {
    const { path } = request;
    relayCalls.push({ path, headers: request.headers ?? {} });

    if (path.endsWith('/v1/models') || path.endsWith('/v1beta/models')) {
      return { data: [{ id: 'test-model' }] };
    }
    if (path.endsWith('/api/tags')) {
      return { models: [{ name: 'test-model' }] };
    }
    // chat / messages / generateContent / api/chat 一律回一个最小成功体
    return {
      choices: [{ message: { content: 'ok' } }],
      content: [{ text: 'ok' }],
      candidates: [{ content: { parts: [{ text: 'ok' }] } }],
      model: 'test-model',
      done: true,
      message: { content: 'ok' },
    };
  }) as unknown as BackendRequestFn;
}

/** 覆盖全部四个内置 provider，各自最容易写错的代表路径与鉴权头。 */
const PROTOCOL_CASES = [
  {
    protocol: 'openai-compatible',
    fetchModelsPath: /^\/api\/v1\/llm\/v1\/models$/,
    testChatPath: /^\/api\/v1\/llm\/v1\/chat\/completions$/,
    /** 各家把 provider key 放在不同的头里（OpenAI 用 Authorization）。 */
    apiKeyHeader: 'Authorization',
    apiKeyPrefix: 'Bearer ',
  },
  {
    protocol: 'anthropic',
    fetchModelsPath: /^\/api\/v1\/llm\/v1\/models$/,
    testChatPath: /^\/api\/v1\/llm\/v1\/messages$/,
    apiKeyHeader: 'x-api-key',
    apiKeyPrefix: '',
  },
  {
    protocol: 'gemini',
    fetchModelsPath: /^\/api\/v1\/llm\/v1beta\/models$/,
    testChatPath: /^\/api\/v1\/llm\/v1beta\/models\/.+:generateContent$/,
    apiKeyHeader: 'x-goog-api-key',
    apiKeyPrefix: '',
  },
  {
    protocol: 'ollama',
    fetchModelsPath: /^\/api\/v1\/llm\/api\/tags$/,
    testChatPath: /^\/api\/v1\/llm\/api\/chat$/,
    /** Ollama 本地无鉴权，不应凭空造出 key 头。 */
    apiKeyHeader: null,
    apiKeyPrefix: '',
  },
] as const;

beforeEach(() => {
  relayCalls.length = 0;
});

describe.each(PROTOCOL_CASES)('provider $protocol 代理路径', (testCase) => {
  const apiKey = testCase.apiKeyHeader === null ? '' : 'sk-provider-key';

  it('fetchModels 请求后端真实注册的 LLM 代理前缀', async () => {
    const backendRequest = installRelayStub();
    const provider = getProviderDefinition(testCase.protocol);

    expect(provider).toBeDefined();
    await provider!.fetchModels('https://upstream.example/v1', apiKey, backendRequest);

    const call = relayCalls.at(-1);
    expect(call?.path).toMatch(testCase.fetchModelsPath);
    expect(call?.path.startsWith(FORBIDDEN_PREFIX)).toBe(false);
  });

  it('testChat 请求后端真实注册的 LLM 代理前缀', async () => {
    const backendRequest = installRelayStub();
    const provider = getProviderDefinition(testCase.protocol);

    expect(provider).toBeDefined();
    await provider!.testChat('https://upstream.example/v1', apiKey, 'test-model', backendRequest);

    const call = relayCalls.at(-1);
    expect(call?.path).toMatch(testCase.testChatPath);
    expect(call?.path.startsWith(FORBIDDEN_PREFIX)).toBe(false);
  });

  it('provider key 放在该协议约定的头里（由后端 LLM 豁免放行）', async () => {
    const backendRequest = installRelayStub();
    const provider = getProviderDefinition(testCase.protocol);

    await provider!.fetchModels('https://upstream.example/v1', apiKey, backendRequest);

    const call = relayCalls.at(-1);
    if (testCase.apiKeyHeader === null) {
      expect(call?.headers.Authorization).toBeUndefined();
    } else {
      expect(call?.headers[testCase.apiKeyHeader]).toBe(`${testCase.apiKeyPrefix}${apiKey}`);
    }
    // 上游地址始终通过 X-LLM-Provider-Url 传递，不直接打用户填的 baseUrl
    expect(call?.headers['X-LLM-Provider-Url']).toBe('https://upstream.example/v1');
  });
});

describe('代理路径前缀', () => {
  it('全部内置 provider 的请求路径都落在后端注册的前缀下', async () => {
    const backendRequest = installRelayStub();

    for (const testCase of PROTOCOL_CASES) {
      const provider = getProviderDefinition(testCase.protocol);
      await provider!.fetchModels('https://upstream.example/v1', 'sk-x', backendRequest);
      await provider!.testChat('https://upstream.example/v1', 'sk-x', 'test-model', backendRequest);
    }

    expect(relayCalls.length).toBe(PROTOCOL_CASES.length * 2);
    for (const call of relayCalls) {
      expect(call.path.startsWith(BACKEND_LLM_PROXY_PREFIX)).toBe(true);
    }
  });
});
