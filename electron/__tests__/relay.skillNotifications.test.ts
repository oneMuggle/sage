import { describe, expect, it, vi, beforeEach } from 'vitest';
import { Readable } from 'node:stream';

vi.mock('node-fetch', async () => {
  const actual = await vi.importActual<typeof import('node-fetch')>('node-fetch');
  return {
    ...actual,
    default: vi.fn(),
  };
});

import nodeFetch from 'node-fetch';
import { relaySkillNotifications } from '../relay';

const mockedFetch = nodeFetch as unknown as ReturnType<typeof vi.fn>;

class MockWebContents {
  sent: Array<{ channel: string; payload: unknown }> = [];
  isDestroyedCalled = 0;
  destroyed = false;
  send(channel: string, payload: unknown) {
    this.sent.push({ channel, payload });
  }
  isDestroyed() {
    this.isDestroyedCalled += 1;
    return this.destroyed;
  }
}

function makeNdjsonReadable(lines: string[]): NodeJS.ReadableStream {
  const body = lines.join('\n') + '\n';
  return Readable.from([body]) as unknown as NodeJS.ReadableStream;
}

function makeNdjsonFetchResponse(lines: string[], init: { status?: number; ok?: boolean } = {}): unknown {
  return {
    ok: init.ok ?? true,
    status: init.status ?? 200,
    body: makeNdjsonReadable(lines),
  };
}

describe('relaySkillNotifications', () => {
  beforeEach(() => {
    mockedFetch.mockReset();
  });

  it('fetches /api/v1/skills/notifications and forwards each NDJSON line as sage:event', async () => {
    mockedFetch.mockResolvedValueOnce(
      makeNdjsonFetchResponse([
        JSON.stringify({ seq: 1, event: { kind: 'skills_rescanned' }, ts: 100 }),
        JSON.stringify({ seq: 2, event: { kind: 'skill_deleted', name: 'x' }, ts: 101 }),
      ]),
    );
    const wc = new MockWebContents();
    const abort = new AbortController();

    await relaySkillNotifications(wc, 'skills:notify', 'http://127.0.0.1:8765', abort.signal);

    expect(mockedFetch).toHaveBeenCalledTimes(1);
    const calledUrl = mockedFetch.mock.calls[0][0];
    expect(calledUrl).toBe('http://127.0.0.1:8765/api/v1/skills/notifications');
    expect(wc.sent.length).toBe(2);
    expect(wc.sent[0].channel).toBe('sage:event:skills:notify');
    expect(wc.sent[0].payload).toEqual({ seq: 1, event: { kind: 'skills_rescanned' }, ts: 100 });
  });

  it('includes Authorization header when authToken provided', async () => {
    mockedFetch.mockResolvedValueOnce(makeNdjsonFetchResponse([]));
    const wc = new MockWebContents();
    const abort = new AbortController();

    await relaySkillNotifications(
      wc,
      'skills:notify',
      'http://127.0.0.1:8765',
      abort.signal,
      'secret-token',
    );

    const headers = mockedFetch.mock.calls[0][1].headers;
    expect(headers.Authorization).toBe('Bearer secret-token');
  });

  it('returns silently when fetch returns non-2xx (e.g. 401)', async () => {
    mockedFetch.mockResolvedValueOnce({ ok: false, status: 401, body: null });
    const wc = new MockWebContents();
    const abort = new AbortController();

    await relaySkillNotifications(wc, 'skills:notify', 'http://127.0.0.1:8765', abort.signal);

    expect(wc.sent.length).toBe(0);
  });

  it('returns silently on network error', async () => {
    const err = new Error('ECONNREFUSED');
    err.name = 'Error';
    mockedFetch.mockRejectedValueOnce(err);
    const wc = new MockWebContents();
    const abort = new AbortController();

    await relaySkillNotifications(wc, 'skills:notify', 'http://127.0.0.1:8765', abort.signal);

    expect(wc.sent.length).toBe(0);
  });

  it('does not send after webContents is destroyed', async () => {
    mockedFetch.mockResolvedValueOnce(
      makeNdjsonFetchResponse([
        JSON.stringify({ seq: 1, event: { kind: 'e1' }, ts: 1 }),
        JSON.stringify({ seq: 2, event: { kind: 'e2' }, ts: 2 }),
      ]),
    );
    const wc = new MockWebContents();
    wc.destroyed = true; // destroyed before processing
    const abort = new AbortController();

    await relaySkillNotifications(wc, 'skills:notify', 'http://127.0.0.1:8765', abort.signal);

    expect(wc.sent.length).toBe(0);
  });
});
