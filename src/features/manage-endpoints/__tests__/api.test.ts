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
  // 默认 handler 不要再 push — wrapper mockFetch 已经做了
  mockFetch(async () => makeJsonResponse(200, { object: 'list', data: [] }));
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
});

describe('testEndpointConnection', () => {
  it('先打 /v1/models 拿模型列表,headers 带 provider url', async () => {
    mockFetch(async () =>
      makeJsonResponse(200, {
        object: 'list',
        data: [{ id: 'qwen2.5:7b', object: 'model', owned_by: 'user' }],
      }),
    );

    const result = await testEndpointConnection(USER_BASE_URL, USER_API_KEY);

    expect(result.success).toBe(true);
    expect(result.message).toContain('1 个模型');
    const modelsCall = fetchCalls.find((c) => c.url.endsWith('/v1/models'));
    expect(modelsCall).toBeDefined();
    const headers = new Headers(modelsCall?.init?.headers);
    expect(headers.get('X-LLM-Provider-Url')).toBe(USER_BASE_URL);
  });
});
