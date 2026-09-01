/**
 * manage-endpoints/api.ts 测试
 *
 * 策略：mock 全局 ``fetch`` 捕获调用方。验证：
 *  1. fetchModels 走代理 baseUrl（不是用户输入的 baseUrl）
 *  2. X-LLM-Provider-Url header 携带真实上游地址
 *  3. Authorization header 透传 apiKey
 *  4. 200 + JSON → 正确解析为 DiscoveredModel[]
 *  5. 上游 500 → 抛出带 HTTP 状态码的 Error
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { fetchModels, testEndpointConnection } from '../api';

const USER_BASE_URL = 'http://192.168.1.10:11434';
const USER_API_KEY = 'sk-test-xyz';
const PROXY_BASE = 'http://localhost:8765/api/v1/llm';

type FetchCall = {
  url: string;
  init: RequestInit | undefined;
};

const fetchCalls: FetchCall[] = [];
const relayRequests: Array<{ path: string; timeoutMs?: number }> = [];

function makeJsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function mockFetch(handler: (url: string, init?: RequestInit) => Promise<Response>) {
  const fn = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const u = String(url);
    fetchCalls.push({ url: u, init });
    return handler(u, init);
  });
  window.fetch = fn as unknown as typeof fetch;
  return fn;
}

beforeEach(() => {
  fetchCalls.length = 0;
  relayRequests.length = 0;
  // 模拟 Electron relay：测试仍可捕获 relay 最终发出的 fetch，renderer 不绕过 bridge。
  (window as unknown as { electronAPI?: unknown }).electronAPI = {
    backendRequest: async (request: { path: string; method?: string; headers?: HeadersInit; body?: unknown; timeoutMs?: number }) => {
      relayRequests.push({ path: request.path, timeoutMs: request.timeoutMs });
      const response = await window.fetch(request.path, {
        method: request.method,
        headers: request.headers,
        body: request.body === undefined ? undefined : JSON.stringify(request.body),
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${await response.text()}`);
      }
      return response.json();
    },
  };
  // 默认 handler 不要再 push — wrapper mockFetch 已经做了
  mockFetch(async (url) =>
    url.endsWith('/v1/chat/completions')
      ? makeJsonResponse(200, { choices: [] })
      : makeJsonResponse(200, { object: 'list', data: [] }),
  );
});

afterEach(() => {
  // 还原到 jsdom 原生 fetch
  // (jsdom 自带 fetch,删除自定义属性即可)
  delete (window as unknown as { fetch?: unknown }).fetch;
});

describe('fetchModels', () => {
  it('调用的是代理 URL,而不是用户输入的 baseUrl', async () => {
    await fetchModels(USER_BASE_URL, USER_API_KEY);

    expect(fetchCalls).toHaveLength(1);
    expect(fetchCalls[0].url).toBe(`${PROXY_BASE}/v1/models`);
    // 关键：绝不能直接打到用户填的 Ollama 地址
    expect(fetchCalls[0].url).not.toContain(USER_BASE_URL);
  });

  it('X-LLM-Provider-Url header 携带真实上游地址', async () => {
    await fetchModels(USER_BASE_URL, USER_API_KEY);

    const headers = new Headers(fetchCalls[0].init?.headers);
    expect(headers.get('X-LLM-Provider-Url')).toBe(USER_BASE_URL);
  });

  it('Authorization header 透传 apiKey', async () => {
    await fetchModels(USER_BASE_URL, USER_API_KEY);

    const headers = new Headers(fetchCalls[0].init?.headers);
    expect(headers.get('Authorization')).toBe(`Bearer ${USER_API_KEY}`);
  });

  it('apiKey 为空时不发 Authorization 头(避免上游 log 噪音)', async () => {
    await fetchModels(USER_BASE_URL, '');

    const headers = new Headers(fetchCalls[0].init?.headers);
    expect(headers.get('Authorization')).toBeNull();
    // X-LLM-Provider-Url 仍要发
    expect(headers.get('X-LLM-Provider-Url')).toBe(USER_BASE_URL);
  });

  it('200 + JSON body → 正确解析为 DiscoveredModel[]', async () => {
    mockFetch(async () =>
      makeJsonResponse(200, {
        object: 'list',
        data: [
          { id: 'qwen2.5:7b', object: 'model', owned_by: 'user' },
          { id: 'llama3.2:3b', object: 'model', owned_by: 'user' },
        ],
      }),
    );

    const models = await fetchModels(USER_BASE_URL, USER_API_KEY);

    expect(models).toHaveLength(2);
    expect(models[0].id).toBe('qwen2.5:7b');
    expect(models[1].id).toBe('llama3.2:3b');
  });

  it('上游 500 → 抛带 HTTP 状态码的 Error', async () => {
    mockFetch(async () => new Response('internal error', { status: 500 }));

    await expect(fetchModels(USER_BASE_URL, USER_API_KEY)).rejects.toThrow(/500/);
  });

  // ============================================================
  // LM Studio 本地端点：用户常填 ``http://127.0.0.1:1234/v1``,空 API key
  // 不发 Authorization,且即便 baseURL 已含 ``/v1`` 也不能拼出 ``/v1/v1/models``。
  // ============================================================
  describe('LM Studio', () => {
    it('discovers an OpenAI-compatible LM Studio endpoint without an API key', async () => {
      mockFetch(async (url) =>
        url.endsWith('/v1/chat/completions')
          ? makeJsonResponse(200, { choices: [] })
          : makeJsonResponse(200, {
              object: 'list',
              data: [{ id: 'qwen2.5-7b-instruct', object: 'model', owned_by: 'user' }],
            }),
      );

      await expect(fetchModels('http://127.0.0.1:1234/v1', '')).resolves.toEqual([
        { id: 'qwen2.5-7b-instruct', capabilities: ['chat'], endpointId: '' },
      ]);
      const last = fetchCalls[fetchCalls.length - 1];
      expect(last.url).toBe(`${PROXY_BASE}/v1/models`);
      const headers = new Headers(last.init?.headers);
      expect(headers.get('Authorization')).toBeNull();
      // provider URL 仍按用户原样透传 — 拼 ``/v1/v1/models`` 由后端
      // ``build_upstream_url`` 去重,不在前端做 (避免职责泄漏)。
      expect(headers.get('X-LLM-Provider-Url')).toBe('http://127.0.0.1:1234/v1');
    });

    it('testEndpointConnection 在 baseURL 已含 /v1 + 空 apiKey 时也能跑通 models 阶段', async () => {
      mockFetch(async (url) =>
        url.endsWith('/v1/chat/completions')
          ? makeJsonResponse(200, { choices: [] })
          : makeJsonResponse(200, {
              object: 'list',
              data: [{ id: 'qwen2.5-7b-instruct', object: 'model', owned_by: 'user' }],
            }),
      );

      // 不带 chatModel → testChatCompletion 不会跑 (被测端点无 chat 候选)
      // 用的是 default first non-embedding, qwen2.5-7b-instruct 是 chat 模型 → 会跑 chat 端点
      const result = await testEndpointConnection('http://127.0.0.1:1234/v1', '');
      expect(result.success).toBe(true);
      expect(relayRequests.find((r) => r.path.endsWith('/v1/chat/completions'))?.timeoutMs).toBe(15000);
      const modelsCall = fetchCalls.find((c) => c.url.endsWith('/v1/models'));
      expect(modelsCall).toBeDefined();
      const headers = new Headers(modelsCall?.init?.headers);
      expect(headers.get('Authorization')).toBeNull();
    });
  });
});

describe('testEndpointConnection', () => {
  it('chat response without choices is not treated as success', async () => {
    mockFetch(async (url) =>
      url.endsWith('/v1/models')
        ? makeJsonResponse(200, { object: 'list', data: [{ id: 'chat-model' }] })
        : makeJsonResponse(200, { status: 'ok' }),
    );

    const result = await testEndpointConnection(USER_BASE_URL, USER_API_KEY);
    expect(result.success).toBe(false);
    expect(result.message).toContain('聊天端点异常');
  });

  it('先打 /v1/models 拿模型列表,headers 带 provider url', async () => {
    mockFetch(async (url) =>
      url.endsWith('/v1/chat/completions')
        ? makeJsonResponse(200, { choices: [] })
        : makeJsonResponse(200, {
            object: 'list',
            data: [{ id: 'qwen2.5:7b', object: 'model', owned_by: 'user' }],
          }),
    );

    const result = await testEndpointConnection(USER_BASE_URL, USER_API_KEY);

    expect(result.success).toBe(true);
    expect(relayRequests.find((r) => r.path.endsWith('/v1/chat/completions'))?.timeoutMs).toBe(15000);
    expect(result.message).toContain('1 个模型');
    const modelsCall = fetchCalls.find((c) => c.url.endsWith('/v1/models'));
    expect(modelsCall).toBeDefined();
    const headers = new Headers(modelsCall?.init?.headers);
    expect(headers.get('X-LLM-Provider-Url')).toBe(USER_BASE_URL);
  });

  it('chatModel 属于被测端点时用它测聊天', async () => {
    mockFetch(async (url) => {
      if (url.endsWith('/v1/models')) {
        return makeJsonResponse(200, {
          object: 'list',
          data: [
            { id: 'agnes-2.0-flash', object: 'model' },
            { id: 'agnes-3-flash', object: 'model' },
          ],
        });
      }
      return makeJsonResponse(200, { choices: [] });
    });

    const result = await testEndpointConnection(USER_BASE_URL, USER_API_KEY, 'agnes-2.0-flash');

    expect(result.success).toBe(true);
    expect(relayRequests.find((r) => r.path.endsWith('/v1/chat/completions'))?.timeoutMs).toBe(15000);
    const chatCall = fetchCalls.find((c) => c.url.endsWith('/v1/chat/completions'));
    expect(chatCall).toBeDefined();
    const body = JSON.parse(String(chatCall?.init?.body)) as { model: string };
    expect(body.model).toBe('agnes-2.0-flash');
  });

  it('chatModel 不属于被测端点 → 回退到被测端点第一个 chat 模型', async () => {
    mockFetch(async (url) => {
      if (url.endsWith('/v1/models')) {
        return makeJsonResponse(200, {
          object: 'list',
          data: [
            { id: 'agnes-2.0-flash', object: 'model' },
            { id: 'agnes-3-flash', object: 'model' },
          ],
        });
      }
      return makeJsonResponse(200, { choices: [] });
    });

    // gemini-3-flash-preview 是另一个端点的全局模型,不在被测端点 models 列表
    const result = await testEndpointConnection(
      USER_BASE_URL,
      USER_API_KEY,
      'gemini-3-flash-preview',
    );

    expect(result.success).toBe(true);
    expect(relayRequests.find((r) => r.path.endsWith('/v1/chat/completions'))?.timeoutMs).toBe(15000);
    const chatCall = fetchCalls.find((c) => c.url.endsWith('/v1/chat/completions'));
    expect(chatCall).toBeDefined();
    const body = JSON.parse(String(chatCall?.init?.body)) as { model: string };
    expect(body.model).toBe('agnes-2.0-flash'); // 被测端点第一个 chat 模型
  });

  it('端点第一个模型是 embedding 时回退到第一个非 embedding 模型', async () => {
    mockFetch(async (url) => {
      if (url.endsWith('/v1/models')) {
        return makeJsonResponse(200, {
          object: 'list',
          data: [
            { id: 'text-embedding-3-large', object: 'model' },
            { id: 'gpt-4o-mini', object: 'model' },
          ],
        });
      }
      return makeJsonResponse(200, { choices: [] });
    });

    const result = await testEndpointConnection(USER_BASE_URL, USER_API_KEY);

    expect(result.success).toBe(true);
    expect(relayRequests.find((r) => r.path.endsWith('/v1/chat/completions'))?.timeoutMs).toBe(15000);
    const chatCall = fetchCalls.find((c) => c.url.endsWith('/v1/chat/completions'));
    expect(chatCall).toBeDefined();
    const body = JSON.parse(String(chatCall?.init?.body)) as { model: string };
    expect(body.model).toBe('gpt-4o-mini'); // 跳过 embedding, 选第一个非 embedding
  });

  it('chatModel 不在列表且被测端点无模型 → 不测聊天, 仅返回发现结果', async () => {
    // beforeEach 默认 handler 返回空 data: []
    const result = await testEndpointConnection(USER_BASE_URL, USER_API_KEY, 'some-model');

    expect(result.success).toBe(true);
    expect(fetchCalls.some((c) => c.url.endsWith('/v1/chat/completions'))).toBe(false);
    expect(result.message).toContain('0 个模型');
  });
});
