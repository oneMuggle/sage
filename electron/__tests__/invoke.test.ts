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
    await expect(invokeBackend('foo_bar', {}, 'http://127.0.0.1:8765')).rejects.toThrow(
      /foo_bar/,
    );
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
});
