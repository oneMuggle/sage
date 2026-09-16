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

import { fetchModels, fetchModelsByProtocol, probeModel, testEndpointConnection } from '../api';

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
    backendRequest: async (request: {
      path: string;
      method?: string;
      headers?: HeadersInit;
      body?: unknown;
      timeoutMs?: number;
    }) => {
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
      expect(relayRequests.find((r) => r.path.endsWith('/v1/chat/completions'))?.timeoutMs).toBe(
        15000,
      );
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
    expect(relayRequests.find((r) => r.path.endsWith('/v1/chat/completions'))?.timeoutMs).toBe(
      15000,
    );
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
    expect(relayRequests.find((r) => r.path.endsWith('/v1/chat/completions'))?.timeoutMs).toBe(
      15000,
    );
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
    expect(relayRequests.find((r) => r.path.endsWith('/v1/chat/completions'))?.timeoutMs).toBe(
      15000,
    );
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
    expect(relayRequests.find((r) => r.path.endsWith('/v1/chat/completions'))?.timeoutMs).toBe(
      15000,
    );
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

/**
 * 上游错误 envelope 翻译测试 — 验证 backend 透传的
 * ``{"detail":{"type":"upstream_error","message":"Upstream returned HTTP <code>."}}``
 * 被前端翻译为用户可读的中文提示, 而不是把整段 IPC + JSON 糊到 toast 上。
 *
 * 测试 mock (line 57) 抛出的 Error 形态是 ``HTTP <code>: <body>``, body 是字符串
 * 形式的 JSON envelope — 与真实 IPC 链路 (sage:backend-request → ``Backend request
 * failed: <code> <body>``) 同源, 区别只是前缀, _parseUpstreamError 的两条正则都
 * 能命中。
 */
describe('upstream error envelope → 中文友好提示', () => {
  const UPSTREAM_401_BODY = JSON.stringify({
    detail: { type: 'upstream_error', message: 'Upstream returned HTTP 401.' },
  });

  it('fetchModels 阶段 upstream 401 → testEndpointConnection 翻译为「API Key 无效或已过期」', async () => {
    mockFetch(
      async () =>
        new Response(UPSTREAM_401_BODY, {
          status: 401,
          headers: { 'content-type': 'application/json' },
        }),
    );

    const result = await testEndpointConnection(USER_BASE_URL, USER_API_KEY);

    expect(result.success).toBe(false);
    expect(result.message).toContain('连接失败');
    expect(result.message).toContain('API Key 无效或已过期');
    // 关键: 整段 JSON envelope 不能漏到用户面前
    expect(result.message).not.toContain('"detail"');
    expect(result.message).not.toContain('upstream_error');
    expect(result.message).not.toContain('Upstream returned HTTP 401.');
  });

  it('chat 阶段 upstream 401 → 翻译提示且不粘 envelope', async () => {
    mockFetch(async (url) => {
      if (url.endsWith('/v1/models')) {
        return makeJsonResponse(200, {
          object: 'list',
          data: [{ id: 'qwen2.5:7b', object: 'model' }],
        });
      }
      // /v1/chat/completions 上游 401
      return new Response(UPSTREAM_401_BODY, {
        status: 401,
        headers: { 'content-type': 'application/json' },
      });
    });

    const result = await testEndpointConnection(USER_BASE_URL, USER_API_KEY);

    expect(result.success).toBe(false);
    expect(result.message).toContain('聊天端点异常');
    expect(result.message).toContain('API Key 无效或已过期');
    expect(result.message).not.toContain('"detail"');
    expect(result.message).not.toContain('upstream_error');
  });

  it('upstream_unreachable envelope (502) → 「上游服务不可达」', async () => {
    const unreachableBody = JSON.stringify({
      detail: {
        type: 'upstream_unreachable',
        message: 'The upstream service could not be reached.',
      },
    });
    mockFetch(
      async () =>
        new Response(unreachableBody, {
          status: 502,
          headers: { 'content-type': 'application/json' },
        }),
    );

    const result = await testEndpointConnection(USER_BASE_URL, USER_API_KEY);

    expect(result.success).toBe(false);
    expect(result.message).toContain('上游服务不可达');
    expect(result.message).not.toContain('"detail"');
  });

  it('upstream_error 404 → 「Base URL 是否正确」', async () => {
    const body = JSON.stringify({
      detail: { type: 'upstream_error', message: 'Upstream returned HTTP 404.' },
    });
    mockFetch(
      async () =>
        new Response(body, { status: 404, headers: { 'content-type': 'application/json' } }),
    );

    const result = await testEndpointConnection(USER_BASE_URL, USER_API_KEY);

    expect(result.success).toBe(false);
    expect(result.message).toContain('404');
    expect(result.message).toContain('Base URL');
    expect(result.message).not.toContain('"detail"');
  });

  it('upstream_error 500 → 「服务异常」', async () => {
    const body = JSON.stringify({
      detail: { type: 'upstream_error', message: 'Upstream returned HTTP 500.' },
    });
    mockFetch(
      async () =>
        new Response(body, { status: 500, headers: { 'content-type': 'application/json' } }),
    );

    const result = await testEndpointConnection(USER_BASE_URL, USER_API_KEY);

    expect(result.success).toBe(false);
    expect(result.message).toContain('500');
    expect(result.message).toContain('服务异常');
    expect(result.message).not.toContain('"detail"');
  });

  it('裸 401 (无 envelope) → 翻译为「上游返回 401」', async () => {
    // fetch 直接抛裸错误而非 JSON envelope — 模拟纯网络错
    mockFetch(async () => new Response('Unauthorized', { status: 401 }));

    const result = await testEndpointConnection(USER_BASE_URL, USER_API_KEY);

    expect(result.success).toBe(false);
    expect(result.message).toContain('401');
    expect(result.message).toContain('API Key');
    expect(result.message).not.toContain('"detail"');
  });

  it('裸网络错误 (fetch throw TypeError) → 兜底为「连接失败: <message>」不抛错', async () => {
    // 模拟 fetch 自身抛错 (非 HTTP 状态码), e.g. DNS / 网络断开
    window.fetch = vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    }) as unknown as typeof fetch;

    const result = await testEndpointConnection(USER_BASE_URL, USER_API_KEY);

    expect(result.success).toBe(false);
    expect(result.message).toContain('连接失败');
    // 兜底保留原 message
    expect(result.message).toContain('Failed to fetch');
  });
});

describe('R33: 协议级模型发现 (anthropic / gemini / ollama)', () => {
  it('anthropic: GET /v1/models 携带 x-api-key + anthropic-version，解析 data[].id', async () => {
    mockFetch(async (url, init) => {
      expect(url).toContain('/v1/models');
      const headers = new Headers(init?.headers);
      expect(headers.get('x-api-key')).toBe('sk-ant');
      expect(headers.get('anthropic-version')).toBe('2023-06-01');
      expect(headers.get('X-LLM-Provider-Url')).toBe(USER_BASE_URL);
      return makeJsonResponse(200, {
        data: [{ id: 'claude-sonnet-4' }, { id: 'claude-haiku-4' }],
      });
    });
    const models = await fetchModelsByProtocol('anthropic', USER_BASE_URL, 'sk-ant');
    expect(models.map((m) => m.id)).toEqual(['claude-sonnet-4', 'claude-haiku-4']);
  });

  it('gemini: GET /v1beta/models 携带 x-goog-api-key，name 剥离 models/ 前缀', async () => {
    mockFetch(async (url, init) => {
      expect(url).toContain('/v1beta/models');
      const headers = new Headers(init?.headers);
      expect(headers.get('x-goog-api-key')).toBe('goog-key');
      return makeJsonResponse(200, {
        models: [{ name: 'models/gemini-2.0-flash' }, { name: 'models/gemini-1.5-pro' }],
      });
    });
    const models = await fetchModelsByProtocol(
      'gemini',
      'https://generativelanguage.googleapis.com',
      'goog-key',
    );
    expect(models.map((m) => m.id)).toEqual(['gemini-2.0-flash', 'gemini-1.5-pro']);
  });

  it('ollama: GET /api/tags 无鉴权头，解析 models[].name', async () => {
    mockFetch(async (url, init) => {
      expect(url).toContain('/api/tags');
      const headers = new Headers(init?.headers);
      expect(headers.get('X-LLM-Provider-Url')).toBe('http://localhost:11434');
      return makeJsonResponse(200, {
        models: [{ name: 'llama3' }, { name: 'qwen2.5:7b' }],
      });
    });
    const models = await fetchModelsByProtocol('ollama', 'http://localhost:11434', '');
    expect(models.map((m) => m.id)).toEqual(['llama3', 'qwen2.5:7b']);
  });

  it('R36: testEndpointConnection 非 openai 协议也做对话级连通测试', async () => {
    mockFetch(async (url, init) => {
      if (url.includes('/api/tags')) {
        return makeJsonResponse(200, { models: [{ name: 'llama3' }] });
      }
      if (url.includes('/api/chat')) {
        const body = JSON.parse(String(init?.body ?? '{}'));
        expect(body.model).toBe('llama3');
        expect(body.stream).toBe(false);
        return makeJsonResponse(200, { message: { content: 'pong' } });
      }
      throw new Error('unexpected fetch: ' + url);
    });
    const result = await testEndpointConnection('http://localhost:11434', '', undefined, 'ollama');
    expect(result.success).toBe(true);
    expect(result.message).toContain('对话连通');
    expect(result.discoveredModels?.[0]?.id).toBe('llama3');
  });
});

describe('R49: 非 openai 协议级补充测试', () => {
  it('anthropic 对话连通：POST /v1/messages 解析 content[0].text', async () => {
    mockFetch(async (url, init) => {
      if (url.includes('/v1/models')) {
        return makeJsonResponse(200, { data: [{ id: 'claude-sonnet-4' }] });
      }
      expect(url).toContain('/v1/messages');
      const body = JSON.parse(String(init?.body ?? '{}'));
      expect(body.model).toBe('claude-sonnet-4');
      expect(body.max_tokens).toBe(16);
      return makeJsonResponse(200, {
        content: [{ type: 'text', text: 'pong from claude' }],
      });
    });
    const result = await testEndpointConnection(
      'https://api.anthropic.com',
      'sk-ant-key',
      'claude-sonnet-4',
      'anthropic',
    );
    expect(result.success).toBe(true);
    expect(result.message).toContain('对话连通');
    expect(result.message).toContain('claude-sonnet-4');
  });

  it('gemini 对话连通：POST generateContent 解析 candidates[0]', async () => {
    mockFetch(async (url, init) => {
      if (url.includes('/v1beta/models')) {
        return makeJsonResponse(200, { models: [{ name: 'models/gemini-2.0-flash' }] });
      }
      expect(url).toContain('generateContent');
      const body = JSON.parse(String(init?.body ?? '{}'));
      expect(body.contents[0].parts[0].text).toBe('ping');
      return makeJsonResponse(200, {
        candidates: [{ content: { parts: [{ text: 'pong from gemini' }] } }],
      });
    });
    const result = await testEndpointConnection(
      'https://generativelanguage.googleapis.com',
      'goog-key',
      'gemini-2.0-flash',
      'gemini',
    );
    expect(result.success).toBe(true);
    expect(result.message).toContain('对话连通');
  });

  it('ollama 对话连通：POST /api/chat stream=false 解析 message.content', async () => {
    mockFetch(async (url, init) => {
      if (url.includes('/api/tags')) {
        return makeJsonResponse(200, { models: [{ name: 'llama3' }] });
      }
      expect(url).toContain('/api/chat');
      const body = JSON.parse(String(init?.body ?? '{}'));
      expect(body.stream).toBe(false);
      return makeJsonResponse(200, { message: { content: 'pong from ollama' } });
    });
    const result = await testEndpointConnection('http://localhost:11434', '', 'llama3', 'ollama');
    expect(result.success).toBe(true);
    expect(result.message).toContain('对话连通');
  });

  it('anthropic 对话端点 401 → 失败 + 中文提示', async () => {
    mockFetch(async (url) => {
      if (url.includes('/v1/models')) {
        return makeJsonResponse(200, { data: [{ id: 'claude-sonnet-4' }] });
      }
      return makeJsonResponse(401, { error: { message: 'invalid x-api-key' } });
    });
    const result = await testEndpointConnection(
      'https://api.anthropic.com',
      'bad-key',
      'claude-sonnet-4',
      'anthropic',
    );
    expect(result.success).toBe(false);
    expect(result.message).toContain('401');
  });

  it('空发现列表 → 降级为仅发现成功（不崩溃）', async () => {
    mockFetch(async () => makeJsonResponse(200, { data: [] }));
    const result = await testEndpointConnection(
      'https://api.anthropic.com',
      'key',
      undefined,
      'anthropic',
    );
    expect(result.success).toBe(true);
    expect(result.message).toContain('无可用于对话测试的模型');
  });
});

describe('probeModel', () => {
  it('POST /api/v1/model-catalog/probe 携带 endpoint_id 和 model_id', async () => {
    mockFetch(async (url, init) => {
      expect(url).toContain('/api/v1/model-catalog/probe');
      const body = JSON.parse(String(init?.body ?? '{}'));
      expect(body.endpoint_id).toBe('ep-1');
      expect(body.model_id).toBe('llama3');
      return makeJsonResponse(200, {
        status: 'success',
        adapter: 'ollama',
        data: { native: 32768, service: null, architecture: 'llama', quantization: 'Q4_K_M' },
        error: null,
      });
    });

    const result = await probeModel('ep-1', 'llama3');
    expect(result.status).toBe('success');
    expect(result.adapter).toBe('ollama');
    expect(result.data?.native).toBe(32768);
    expect(result.data?.architecture).toBe('llama');
  });

  it('unsupported 状态（OpenAI-compatible 服务）返回正确', async () => {
    mockFetch(async () =>
      makeJsonResponse(200, {
        status: 'unsupported',
        adapter: 'openai-compatible',
        data: null,
        error: 'OpenAI-compatible services do not expose model metadata via /v1/models',
      }),
    );

    const result = await probeModel('ep-1', 'gpt-4o');
    expect(result.status).toBe('unsupported');
    expect(result.data).toBeNull();
    expect(result.error).toContain('do not expose');
  });

  it('error 状态（网络错误）返回正确', async () => {
    mockFetch(async () =>
      makeJsonResponse(200, {
        status: 'error',
        adapter: 'ollama',
        data: null,
        error: 'connection refused',
      }),
    );

    const result = await probeModel('ep-1', 'llama3');
    expect(result.status).toBe('error');
    expect(result.error).toContain('connection refused');
  });
});
