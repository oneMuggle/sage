import { describe, expect, it, vi, beforeEach } from 'vitest';
import { Readable } from 'node:stream';

// Mock node-fetch BEFORE importing the module under test.
// We keep `Response` real (it's a WHATWG-compatible class with .ok / .body
// — node-fetch@2 implements the same interface as global Response). The
// only thing we mock is the default `fetch` so we can assert relay.ts uses
// the imported `node-fetch` (not a global `fetch` that doesn't exist in
// Electron's Node 16).
vi.mock('node-fetch', async () => {
  const actual = await vi.importActual<typeof import('node-fetch')>('node-fetch');
  return {
    ...actual,
    default: vi.fn(),
  };
});

import nodeFetch from 'node-fetch';
import { parseNdjsonStream, relayChatStream } from '../relay';

const mockedFetch = nodeFetch as unknown as ReturnType<typeof vi.fn>;

class MockWebContents {
  sent: Array<{ channel: string; payload: unknown }> = [];
  send(channel: string, payload: unknown) {
    this.sent.push({ channel, payload });
  }
}

/**
 * Build a Node Readable stream that emits NDJSON lines then ends.
 * `Readable.from(...)` returns Web ReadableStream per Node 18+ types but
 * Node Readable at runtime in Node 16 — cast through unknown for tests.
 */
function makeNdjsonReadable(lines: string[]): NodeJS.ReadableStream {
  const body = lines.join('\n') + '\n';
  return Readable.from([body]) as unknown as NodeJS.ReadableStream;
}

/** Build a fetch Response shape that node-fetch would return. */
function makeNdjsonFetchResponse(
  lines: string[],
  init: { status?: number; ok?: boolean } = {},
): unknown {
  const ok = init.ok ?? true;
  const status = init.status ?? 200;
  return {
    ok,
    status,
    body: makeNdjsonReadable(lines),
  };
}

describe('parseNdjsonStream', () => {
  it('parses each non-empty line as a separate JSON event', async () => {
    const stream = makeNdjsonReadable([
      JSON.stringify({ state: 'thinking', iteration: 0 }),
      JSON.stringify({ state: 'acting', tool_call: { name: 'web_search' } }),
      '',
      JSON.stringify({ state: 'done', content: 'answer' }),
    ]);
    const events: unknown[] = [];
    await parseNdjsonStream(stream, (e) => events.push(e));
    expect(events).toEqual([
      { state: 'thinking', iteration: 0 },
      { state: 'acting', tool_call: { name: 'web_search' } },
      { state: 'done', content: 'answer' },
    ]);
  });

  it('forwards raw non-JSON lines as { raw }', async () => {
    const stream = makeNdjsonReadable(['not json', JSON.stringify({ state: 'done' })]);
    const events: unknown[] = [];
    await parseNdjsonStream(stream, (e) => events.push(e));
    expect(events).toEqual([{ raw: 'not json' }, { state: 'done' }]);
  });

  it('honors AbortSignal that fires before consumption (resolves without consuming)', async () => {
    // If the signal is already aborted when parseNdjsonStream is called, we
    // must destroy the stream and return immediately without consuming it.
    const ac = new AbortController();
    ac.abort();
    const stream = Readable.from(['{"state":"thinking"}\n']) as unknown as NodeJS.ReadableStream;
    const events: unknown[] = [];
    await expect(
      parseNdjsonStream(stream, (e) => events.push(e), ac.signal),
    ).resolves.toBeUndefined();
    // Stream destroyed before read → no events delivered.
    expect(events).toEqual([]);
  });

  it('resolves when stream ends naturally (no abort)', async () => {
    const stream = Readable.from(['{"state":"done"}\n']) as unknown as NodeJS.ReadableStream;
    const events: unknown[] = [];
    await expect(
      parseNdjsonStream(stream, (e) => events.push(e)),
    ).resolves.toBeUndefined();
    expect(events).toEqual([{ state: 'done' }]);
  });

  it('does nothing when body is null', async () => {
    const events: unknown[] = [];
    await parseNdjsonStream(null, (e) => events.push(e));
    expect(events).toEqual([]);
  });
});

describe('relayChatStream (I2: attach to existing stream via GET)', () => {
  beforeEach(() => {
    mockedFetch.mockReset();
  });

  it('GETs /chat/stream/{streamId} via node-fetch with no body, relays NDJSON to webContents', async () => {
    const wc = new MockWebContents();
    mockedFetch.mockResolvedValueOnce(
      makeNdjsonFetchResponse([JSON.stringify({ state: 'done', content: 'ok' })]),
    );

    await relayChatStream(
      wc as unknown as Electron.WebContents,
      'chat-stream-abc',
      'abc',
      'http://127.0.0.1:8765',
      new AbortController().signal,
    );

    // I2 关键: 不再 POST + body,改为 GET + path param streamId
    expect(mockedFetch).toHaveBeenCalledWith(
      'http://127.0.0.1:8765/api/v1/chat/stream/abc',
      expect.objectContaining({
        method: 'GET',
      }),
    );
    const callArgs = mockedFetch.mock.calls[0][1] as RequestInit;
    expect(callArgs.body).toBeUndefined();
    expect(wc.sent).toEqual([
      { channel: 'sage:event:chat-stream-abc', payload: { state: 'done', content: 'ok' } },
    ]);
  });

  it('url-encodes streamId with special characters', async () => {
    const wc = new MockWebContents();
    mockedFetch.mockResolvedValueOnce(
      makeNdjsonFetchResponse([JSON.stringify({ state: 'done' })]),
    );
    await relayChatStream(
      wc as unknown as Electron.WebContents,
      'chat-stream-x',
      'sid/with/slashes',
      'http://127.0.0.1:8765',
      new AbortController().signal,
    );
    expect(mockedFetch).toHaveBeenCalledWith(
      'http://127.0.0.1:8765/api/v1/chat/stream/sid%2Fwith%2Fslashes',
      expect.anything(),
    );
  });

  it('does nothing if backend returns non-OK (no error thrown)', async () => {
    const wc = new MockWebContents();
    mockedFetch.mockResolvedValueOnce({ ok: false, status: 500, body: null });
    await relayChatStream(
      wc as unknown as Electron.WebContents,
      'chat-stream-abc',
      'abc',
      'http://127.0.0.1:8765',
      new AbortController().signal,
    );
    expect(wc.sent).toEqual([]);
  });

  it('does nothing on network error (does not crash main process)', async () => {
    const wc = new MockWebContents();
    mockedFetch.mockRejectedValueOnce(new Error('ECONNREFUSED'));
    await relayChatStream(
      wc as unknown as Electron.WebContents,
      'chat-stream-abc',
      'abc',
      'http://127.0.0.1:8765',
      new AbortController().signal,
    );
    expect(wc.sent).toEqual([]);
  });
});
