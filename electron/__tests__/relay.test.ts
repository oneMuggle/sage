import { describe, expect, it, vi, beforeEach } from 'vitest';
import { parseNdjsonStream, relayChatStream } from '../relay';

class MockWebContents {
  sent: Array<{ channel: string; payload: unknown }> = [];
  send(channel: string, payload: unknown) {
    this.sent.push({ channel, payload });
  }
}

function makeNdjsonResponse(lines: string[]): Response {
  const body = lines.join('\n') + '\n';
  return new Response(body, {
    status: 200,
    headers: { 'content-type': 'application/x-ndjson' },
  });
}

describe('parseNdjsonStream', () => {
  it('parses each non-empty line as a separate JSON event', async () => {
    const res = makeNdjsonResponse([
      JSON.stringify({ state: 'thinking', iteration: 0 }),
      JSON.stringify({ state: 'acting', tool_call: { name: 'web_search' } }),
      '',
      JSON.stringify({ state: 'done', content: 'answer' }),
    ]);
    const events: unknown[] = [];
    await parseNdjsonStream(res, (e) => events.push(e));
    expect(events).toEqual([
      { state: 'thinking', iteration: 0 },
      { state: 'acting', tool_call: { name: 'web_search' } },
      { state: 'done', content: 'answer' },
    ]);
  });

  it('forwards raw non-JSON lines as { raw }', async () => {
    const res = makeNdjsonResponse(['not json', JSON.stringify({ state: 'done' })]);
    const events: unknown[] = [];
    await parseNdjsonStream(res, (e) => events.push(e));
    expect(events).toEqual([{ raw: 'not json' }, { state: 'done' }]);
  });

  it('honors AbortSignal mid-stream', async () => {
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('{"state":"thinking"}\n'));
        controller.enqueue(new TextEncoder().encode('{"state":"act'));
        // never closes — caller aborts
      },
    });
    const res = new Response(stream, { status: 200 });
    const ac = new AbortController();
    const events: unknown[] = [];
    const p = parseNdjsonStream(res, (e) => events.push(e), ac.signal);
    ac.abort();
    await p;
    expect(events.length).toBeGreaterThanOrEqual(1);
  });
});

describe('relayChatStream (I2: attach to existing stream via GET)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('GETs /chat/stream/{streamId} with no body, relays NDJSON to webContents', async () => {
    const wc = new MockWebContents();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        makeNdjsonResponse([JSON.stringify({ state: 'done', content: 'ok' })]),
      );
    vi.stubGlobal('fetch', fetchMock);

    await relayChatStream(
      wc as unknown as Electron.WebContents,
      'chat-stream-abc',
      'abc',
      'http://127.0.0.1:8765',
      new AbortController().signal,
    );

    // I2 关键: 不再 POST + body,改为 GET + path param streamId
    expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:8765/chat/stream/abc',
      expect.objectContaining({
        method: 'GET',
      }),
    );
    // 确保没有 POST body(GET 也不应带 body)
    const callArgs = fetchMock.mock.calls[0][1] as RequestInit;
    expect(callArgs.body).toBeUndefined();
    expect(wc.sent).toEqual([
      { channel: 'sage:event:chat-stream-abc', payload: { state: 'done', content: 'ok' } },
    ]);
  });

  it('url-encodes streamId with special characters', async () => {
    const wc = new MockWebContents();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(makeNdjsonResponse([JSON.stringify({ state: 'done' })]));
    vi.stubGlobal('fetch', fetchMock);

    await relayChatStream(
      wc as unknown as Electron.WebContents,
      'chat-stream-x',
      'sid/with/slashes',
      'http://127.0.0.1:8765',
      new AbortController().signal,
    );

    expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:8765/chat/stream/sid%2Fwith%2Fslashes',
      expect.anything(),
    );
  });

  it('does nothing if backend returns non-OK (no error thrown)', async () => {
    const wc = new MockWebContents();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response('boom', { status: 500 })));
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
    vi.stubGlobal('fetch', vi.fn().mockRejectedValueOnce(new Error('ECONNREFUSED')));
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
