import { describe, expect, it, vi, beforeEach } from 'vitest';

// Mock node-fetch BEFORE importing the module under test.
// We keep named exports (Response, Headers, FetchError) real so Response
// parsing in main.js still works; only the default `fetch` is mockable.
vi.mock('node-fetch', async () => {
  const actual = await vi.importActual<typeof import('node-fetch')>('node-fetch');
  return {
    ...actual,
    default: vi.fn(),
  };
});

import nodeFetch from 'node-fetch';
import { invokeBackend } from '../invoke';

const mockedFetch = nodeFetch as unknown as ReturnType<typeof vi.fn>;

function mockJsonResponse(body: unknown, init?: { status?: number; ok?: boolean }) {
  const ok = init?.ok ?? true;
  const status = init?.status ?? 200;
  return {
    ok,
    status,
    json: async () => body,
    text: async () => (typeof body === 'string' ? body : JSON.stringify(body)),
  };
}

describe('invokeBackend', () => {
  beforeEach(() => {
    mockedFetch.mockReset();
  });

  it('throws UnknownIpcCommandError for unknown cmd', async () => {
    await expect(invokeBackend('foo_bar', {}, 'http://127.0.0.1:8765')).rejects.toThrow(/foo_bar/);
    expect(mockedFetch).not.toHaveBeenCalled();
  });

  it('GET /api/v1/sessions?limit=100&offset=0 with no body and parses JSON response', async () => {
    mockedFetch.mockResolvedValueOnce(mockJsonResponse([{ id: 's1' }]));
    const result = await invokeBackend('list_sessions', {}, 'http://127.0.0.1:8765');
    expect(mockedFetch).toHaveBeenCalledTimes(1);
    expect(mockedFetch).toHaveBeenCalledWith(
      'http://127.0.0.1:8765/api/v1/sessions?limit=100&offset=0',
      expect.objectContaining({ method: 'GET' }),
    );
    const init = mockedFetch.mock.calls[0][1] as RequestInit;
    expect(init.body).toBeUndefined();
    expect(result).toEqual([{ id: 's1' }]);
  });

  it('passes custom limit/offset through to query string', async () => {
    mockedFetch.mockResolvedValueOnce(mockJsonResponse([]));
    await invokeBackend('list_sessions', { limit: 5, offset: 20 }, 'http://127.0.0.1:8765');
    expect(mockedFetch).toHaveBeenCalledWith(
      'http://127.0.0.1:8765/api/v1/sessions?limit=5&offset=20',
      expect.anything(),
    );
  });

  it('POST /api/v1/sessions serializes args as JSON body and sends Content-Type', async () => {
    mockedFetch.mockResolvedValueOnce(mockJsonResponse({ id: 'new' }));
    await invokeBackend('create_session', { title: 'hello' }, 'http://x');
    expect(mockedFetch).toHaveBeenCalledWith(
      'http://x/api/v1/sessions',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ title: 'hello' }),
      }),
    );
  });

  it('DELETE sends no body', async () => {
    mockedFetch.mockResolvedValueOnce(mockJsonResponse({ ok: true }));
    await invokeBackend('delete_session', { id: 's1' }, 'http://x');
    expect(mockedFetch).toHaveBeenCalledWith(
      'http://x/api/v1/sessions/s1',
      expect.objectContaining({ method: 'DELETE' }),
    );
    const init = mockedFetch.mock.calls[0][1] as RequestInit;
    expect(init.body).toBeUndefined();
  });

  it('throws on non-OK response with status code + body text', async () => {
    mockedFetch.mockResolvedValueOnce(mockJsonResponse('boom', { ok: false, status: 500 }));
    await expect(invokeBackend('list_sessions', {}, 'http://x')).rejects.toThrow(/500.*boom/);
  });

  it('GET /api/v1/sessions/:id url-encodes ids with special characters', async () => {
    mockedFetch.mockResolvedValueOnce(mockJsonResponse({ id: 's/1' }));
    await invokeBackend('get_session', { id: 's/1' }, 'http://x');
    expect(mockedFetch).toHaveBeenCalledWith('http://x/api/v1/sessions/s%2F1', expect.anything());
  });

  // ====================================================================
  // I4: 回归保护 — IPC bridge 必须把 camelCase args 转成 snake_case body
  // 背景: 前端用 sessionId / apiKey / apiUrl / maxContext (JS 习惯)
  //       后端 Pydantic ChatRequest 要 session_id / api_key / api_url / max_context
  //       bridge 不转 → 422 missing session_id。锁定 bridge 做翻译。
  // ====================================================================

  it('converts camelCase body keys to snake_case for POST', async () => {
    mockedFetch.mockResolvedValueOnce(mockJsonResponse({ streamId: 'sid-1' }));
    await invokeBackend(
      'agent_chat_stream',
      {
        sessionId: 'ce12659d-42d6-4a1f-a846-b2c914df0444',
        message: '你好',
        apiKey: 'sk-test',
        apiUrl: 'https://gcli.ggchan.dev/',
        model: 'gemini-2.5-pro',
        maxContext: 4096,
        temperature: 0.7,
      },
      'http://127.0.0.1:8765',
    );
    const init = mockedFetch.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(init.body as string);
    // 关键: 全部转 snake_case
    expect(body).toEqual({
      session_id: 'ce12659d-42d6-4a1f-a846-b2c914df0444',
      message: '你好',
      api_key: 'sk-test',
      api_url: 'https://gcli.ggchan.dev/',
      model: 'gemini-2.5-pro',
      max_context: 4096,
      temperature: 0.7,
    });
    // 没有任何 camelCase 残留
    expect(body).not.toHaveProperty('sessionId');
    expect(body).not.toHaveProperty('apiKey');
    expect(body).not.toHaveProperty('apiUrl');
    expect(body).not.toHaveProperty('maxContext');
  });

  it('converts multi-word camelCase keys (e.g. hasFoo → has_foo)', async () => {
    mockedFetch.mockResolvedValueOnce(mockJsonResponse({ id: 'new' }));
    await invokeBackend(
      'create_session',
      { title: 'x', hasApiKey: false, newName: 'n' },
      'http://x',
    );
    const init = mockedFetch.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(init.body as string);
    expect(body).toEqual({ title: 'x', has_api_key: false, new_name: 'n' });
  });

  it('leaves single-word keys and already-snake_case keys untouched', async () => {
    mockedFetch.mockResolvedValueOnce(mockJsonResponse({ id: 'new' }));
    await invokeBackend(
      'create_session',
      { title: 'hello', already_snake: 1, max_iterations: 5 },
      'http://x',
    );
    const init = mockedFetch.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(init.body as string);
    expect(body).toEqual({ title: 'hello', already_snake: 1, max_iterations: 5 });
  });

  it('converts nested object keys recursively', async () => {
    mockedFetch.mockResolvedValueOnce(mockJsonResponse({ id: 'new' }));
    await invokeBackend(
      'create_session',
      {
        userId: 'u1',
        nestedConfig: { apiKey: 'k', maxTokens: 100, ok: true },
        title: 'x',
      },
      'http://x',
    );
    const init = mockedFetch.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(init.body as string);
    expect(body).toEqual({
      user_id: 'u1',
      nested_config: { api_key: 'k', max_tokens: 100, ok: true },
      title: 'x',
    });
  });

  it('converts object keys inside arrays', async () => {
    mockedFetch.mockResolvedValueOnce(mockJsonResponse({ id: 'new' }));
    await invokeBackend(
      'create_session',
      { title: 'x', messages: [{ sessionId: 's1', role: 'user' }] },
      'http://x',
    );
    const init = mockedFetch.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(init.body as string);
    expect(body.messages).toEqual([{ session_id: 's1', role: 'user' }]);
  });

  it('does NOT transform GET request query args (only body args)', async () => {
    // list_sessions 是 GET,query string 里的 limit/offset 走 path builder
    // 那些 key 不应该被当成 body key 转换
    mockedFetch.mockResolvedValueOnce(mockJsonResponse([]));
    await invokeBackend('list_sessions', { limit: 5, offset: 20 }, 'http://x');
    const init = mockedFetch.mock.calls[0][1] as RequestInit;
    expect(init.body).toBeUndefined();
  });
});
