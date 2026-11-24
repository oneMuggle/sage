import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  backendRequestViaHttp,
  getWebAuthHeaders,
  getWebCapabilityHeaders,
  invokeViaHttp,
  listenViaHttp,
  WebDesktopOnlyError,
} from '../webTransport';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function stubWindow(token?: string) {
  vi.stubGlobal('window', {
    localStorage: { getItem: () => token ?? null },
  });
}

describe('webTransport auth headers', () => {
  it('returns Bearer header when a token is stored', () => {
    stubWindow('tok-1');
    expect(getWebAuthHeaders()).toEqual({ Authorization: 'Bearer tok-1' });
  });

  it('returns no header without a token', () => {
    stubWindow();
    expect(getWebAuthHeaders()).toEqual({});
  });

  it('getWebCapabilityHeaders 放入 X-Sage-Local-Authorization（不占用 Authorization）', () => {
    stubWindow('tok-1');
    expect(getWebCapabilityHeaders()).toEqual({ 'X-Sage-Local-Authorization': 'Bearer tok-1' });
  });
});

describe('invokeViaHttp', () => {
  it('resolves a known command through COMMAND_ROUTES with snake_case body', async () => {
    stubWindow('tok-1');
    const fetchStub = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ fine: true }),
    });
    vi.stubGlobal('fetch', fetchStub);

    await expect(invokeViaHttp('create_session', { projectId: 'p1' })).resolves.toEqual({
      fine: true,
    });
    const [url, init] = fetchStub.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/v1/sessions');
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toEqual({ project_id: 'p1' });
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok-1');
  });

  it('throws WebDesktopOnlyError for Electron-only channels', async () => {
    stubWindow('tok-1');
    await expect(invokeViaHttp('browser_panel', {})).rejects.toBeInstanceOf(WebDesktopOnlyError);
  });

  it('surfaces backend detail with status_code on HTTP errors', async () => {
    stubWindow();
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        text: async () => JSON.stringify({ detail: '参数不合法' }),
      }),
    );
    const err = (await invokeViaHttp('list_sessions', {}).catch((e) => e)) as Error & {
      status_code?: number;
    };
    expect(err.status_code).toBe(422);
    expect(err.message).toContain('参数不合法');
    expect(err.message).toContain('HTTP 422');
  });

  it('returns null for 204 responses', async () => {
    stubWindow();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 204 }));
    await expect(invokeViaHttp('list_sessions', {})).resolves.toBeNull();
  });
});

describe('backendRequestViaHttp', () => {
  it('通过 X-Sage-Local-Authorization 携带本地能力，支持 text 响应与 timeout', async () => {
    stubWindow('tok-1');
    const fetchStub = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => 'hello',
    });
    vi.stubGlobal('fetch', fetchStub);

    await expect(
      backendRequestViaHttp<string>({ path: '/api/v1/x', responseType: 'text' }),
    ).resolves.toBe('hello');
    const [url, init] = fetchStub.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/v1/x');
    const headers = new Headers(init.headers);
    expect(headers.get('X-Sage-Local-Authorization')).toBe('Bearer tok-1');
    // 调用方没提供 Authorization → 不再被本地 token 占用（避免 LLM 代理路径冲突）
    expect(headers.get('Authorization')).toBeNull();
  });

  it('LLM 代理场景：调用方提供的 Authorization（上游 API Key）不被本地 token 覆盖', async () => {
    stubWindow('local-capability');
    const fetchStub = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ object: 'list', data: [] }),
    });
    vi.stubGlobal('fetch', fetchStub);

    await backendRequestViaHttp({
      path: '/api/v1/llm/v1/models',
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
        'X-LLM-Provider-Url': 'https://api.openai.com/v1',
        Authorization: 'Bearer sk-upstream-key',
      },
    });
    const [, init] = fetchStub.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    // 上游 API Key 必须原样透传（不被本地 token 覆盖）
    expect(headers.get('Authorization')).toBe('Bearer sk-upstream-key');
    // 本地能力走独立的 X-Sage-Local-Authorization（与 Electron 中继语义一致）
    expect(headers.get('X-Sage-Local-Authorization')).toBe('Bearer local-capability');
    expect(headers.get('X-LLM-Provider-Url')).toBe('https://api.openai.com/v1');
  });

  it('大小写不敏感的 header 合并：调用方大小写不同也不会产生双份', async () => {
    stubWindow('tok');
    const fetchStub = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => '',
    });
    vi.stubGlobal('fetch', fetchStub);

    await backendRequestViaHttp({
      path: '/api/v1/x',
      headers: { authorization: 'Bearer caller-key' },
      responseType: 'text',
    });
    const [, init] = fetchStub.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    // 调用方 Authorization 原样保留；本地能力仍在 X-Sage-Local-Authorization
    expect(headers.get('Authorization')).toBe('Bearer caller-key');
    expect(headers.get('X-Sage-Local-Authorization')).toBe('Bearer tok');
  });
});

describe('listenViaHttp', () => {
  it('no-ops for events without a transport', async () => {
    const stop = await listenViaHttp('backend:ready', () => {});
    expect(typeof stop).toBe('function');
  });

  it('relays NDJSON lines for shell streams', async () => {
    stubWindow('tok-1');
    const encoder = new TextEncoder();
    let sent = false;
    const reader = {
      read: async () => {
        if (sent) return { done: true, value: undefined };
        sent = true;
        return { done: false, value: encoder.encode('{"type":"output"}\n{"type":"exit"}\n') };
      },
    };
    const fetchStub = vi
      .fn()
      .mockResolvedValue({ ok: true, status: 200, body: { getReader: () => reader } });
    vi.stubGlobal('fetch', fetchStub);

    const seen: unknown[] = [];
    await listenViaHttp('shell-stream-s1', (e) => seen.push(e.payload));
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(fetchStub).toHaveBeenCalledWith(
      '/api/v1/shells/s1/stream',
      expect.objectContaining({ method: 'GET' }),
    );
    expect(seen).toEqual([{ type: 'output' }, { type: 'exit' }]);
  });
});
