import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';

import { listen } from '../../../shared/api/desktopEvent';
import { wikiChatStream, cancelWikiChatStream } from '../../../shared/api-client/wiki';
import { useWikiChatStream } from '../useWikiChatStream';

const mocks = vi.hoisted(() => ({
  wikiChatStream: vi.fn(),
  cancelWikiChatStream: vi.fn().mockResolvedValue(undefined),
}));

vi.mock('../../../shared/api-client/wiki', () => ({
  wikiChatStream: mocks.wikiChatStream,
  cancelWikiChatStream: mocks.cancelWikiChatStream,
}));

// Capture registered listeners per event so tests can fire payloads.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const listeners: Record<string, Array<(e: { payload: any }) => void>> = {};

vi.mock('../../../shared/api/desktopEvent', () => ({
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  listen: vi.fn(async (event: string, handler: (e: { payload: any }) => void) => {
    listeners[event] = listeners[event] || [];
    listeners[event].push(handler);
    return () => {
      listeners[event] = listeners[event].filter((h) => h !== handler);
    };
  }),
}));

function fire(event: string, payload: unknown) {
  (listeners[event] || []).forEach((h) => h({ payload }));
}

describe('useWikiChatStream', () => {
  beforeEach(() => {
    mocks.wikiChatStream.mockReset();
    mocks.cancelWikiChatStream.mockReset().mockResolvedValue(undefined);
    Object.keys(listeners).forEach((k) => delete listeners[k]);
  });

  it('subscribes before starting a request that completes synchronously', async () => {
    mocks.wikiChatStream.mockImplementation(async () => {
      fire('wiki-chat-stream-fast-chunk', 'instant');
      fire('wiki-chat-stream-fast-done', { citations: [], sources: [] });
      return { streamId: 'fast' };
    });
    const request = {
      query: 'q',
      projectPath: '/p',
      llmBaseUrl: '',
      llmApiKey: '',
      llmModel: 'm',
      embedBaseUrl: '',
      embedApiKey: '',
      embedModel: 'm',
    };
    const { result } = renderHook(() => useWikiChatStream('fast', request));
    await act(async () => {});
    expect(result.current.answer).toBe('instant');
    expect(result.current.completed).toBe(true);
  });

  it('does not start after unmount while subscriptions are pending', async () => {
    let resolve!: (fn: () => void) => void;
    const cleanup = vi.fn();
    vi.mocked(listen).mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    const request = {
      query: 'q',
      projectPath: '/p',
      llmBaseUrl: '',
      llmApiKey: '',
      llmModel: 'm',
      embedBaseUrl: '',
      embedApiKey: '',
      embedModel: 'm',
    };
    const { unmount } = renderHook(() => useWikiChatStream('pending', request));
    unmount();
    await act(async () => {
      resolve(cleanup);
    });
    expect(wikiChatStream).not.toHaveBeenCalled();
    expect(cleanup).toHaveBeenCalledOnce();
  });

  it('does not start if one listener fails and removes other listeners', async () => {
    vi.mocked(listen).mockRejectedValueOnce(new Error('subscription failed'));
    const request = {
      query: 'q',
      projectPath: '/p',
      llmBaseUrl: '',
      llmApiKey: '',
      llmModel: 'm',
      embedBaseUrl: '',
      embedApiKey: '',
      embedModel: 'm',
    };
    const { result } = renderHook(() => useWikiChatStream('failed', request));
    await act(async () => {});
    expect(wikiChatStream).not.toHaveBeenCalled();
    expect(result.current.error).toContain('subscription failed');
    expect(listeners['wiki-chat-stream-failed-done']).toHaveLength(0);
  });

  it('receives a synchronous startup error', async () => {
    mocks.wikiChatStream.mockImplementation(async () => {
      fire('wiki-chat-stream-failed-error', { message: 'backend failed' });
      return { streamId: 'failed' };
    });
    const request = {
      query: 'q',
      projectPath: '/p',
      llmBaseUrl: '',
      llmApiKey: '',
      llmModel: 'm',
      embedBaseUrl: '',
      embedApiKey: '',
      embedModel: 'm',
    };
    const { result } = renderHook(() => useWikiChatStream('failed', request));
    await act(async () => {});
    expect(result.current.error).toBe('backend failed');
    expect(result.current.completed).toBe(true);
  });

  it('accumulates answer from chunk events and keeps streaming', async () => {
    const { result } = renderHook(({ streamId }) => useWikiChatStream(streamId), {
      initialProps: { streamId: 's1' as string | null },
    });
    await act(async () => {
      fire('wiki-chat-stream-s1-chunk', 'Hello');
      fire('wiki-chat-stream-s1-chunk', ' world');
    });
    expect(result.current.answer).toBe('Hello world');
    expect(result.current.streaming).toBe(true);
    expect(result.current.error).toBeNull();
  });

  it('keeps retrieved sources separate from cited evidence', async () => {
    const { result } = renderHook(() => useWikiChatStream('sources'));
    const source = {
      id: 'S1',
      path: 'wiki/a.md',
      title: 'A',
      excerpt: 'Evidence',
      content_hash: 'abc',
      line_start: 1,
      line_end: 1,
    };
    await act(async () => {
      fire('wiki-chat-stream-sources-done', { citations: [], sources: [source] });
    });
    expect(result.current.sources).toEqual([source]);
    expect(result.current.citations).toEqual([]);
    expect(result.current.completed).toBe(true);
  });

  it('sets streaming=false and citations on done event', async () => {
    const { result } = renderHook(({ streamId }) => useWikiChatStream(streamId), {
      initialProps: { streamId: 's1' as string | null },
    });
    const citation = {
      id: 'S1',
      path: 'wiki/a.md',
      title: 'A',
      excerpt: 'text',
      content_hash: 'hash',
      line_start: 1,
      line_end: 1,
    };
    await act(async () => {
      fire('wiki-chat-stream-s1-done', { citations: [citation], sources: [citation] });
    });
    expect(result.current.streaming).toBe(false);
    expect(result.current.citations).toEqual([citation]);
  });

  // Electron main relays 4 error payload shapes, but only 2 distinct runtime
  // shapes reach the renderer: an object `{ error: string }` (HTTP non-2xx,
  // non-AbortError catch, synthetic NDJSON-parse error) and a bare `string`
  // (backend error event data relayed verbatim). Both must normalize to
  // state.error: string.

  it('normalizes object-shape error payload { error } to state.error', async () => {
    const { result } = renderHook(({ streamId }) => useWikiChatStream(streamId), {
      initialProps: { streamId: 's1' as string | null },
    });
    await act(async () => {
      fire('wiki-chat-stream-s1-error', { error: 'LLM timeout' });
    });
    expect(result.current.error).toBe('LLM timeout');
    expect(result.current.streaming).toBe(false);
  });

  it('normalizes string error payload to state.error', async () => {
    const { result } = renderHook(({ streamId }) => useWikiChatStream(streamId), {
      initialProps: { streamId: 's1' as string | null },
    });
    await act(async () => {
      fire('wiki-chat-stream-s1-error', 'invalid NDJSON line');
    });
    expect(result.current.error).toBe('invalid NDJSON line');
    expect(result.current.streaming).toBe(false);
  });

  it('clears completed state when detached and ignores old stream events', async () => {
    const { result, rerender } = renderHook(({ id }) => useWikiChatStream(id), {
      initialProps: { id: 'old' as string | null },
    });
    await act(async () => {
      fire('wiki-chat-stream-old-chunk', 'old answer');
    });
    await act(async () => {
      rerender({ id: null });
    });
    await act(async () => {
      fire('wiki-chat-stream-old-chunk', 'late');
    });
    expect(result.current.answer).toBe('');
    expect(result.current.completed).toBe(false);
  });

  it('unlistens all events when streamId becomes null', async () => {
    const { rerender } = renderHook(({ streamId }) => useWikiChatStream(streamId), {
      initialProps: { streamId: 's1' as string | null },
    });
    // Flush the pending listen() promises so the unlisten fns (assigned in
    // .then callbacks) are captured before cleanup runs on rerender.
    await act(async () => {});
    expect(listeners['wiki-chat-stream-s1-chunk']?.length).toBe(1);
    expect(listeners['wiki-chat-stream-s1-done']?.length).toBe(1);
    expect(listeners['wiki-chat-stream-s1-error']?.length).toBe(1);

    await act(async () => {
      rerender({ streamId: null });
    });

    expect(listeners['wiki-chat-stream-s1-chunk']?.length).toBe(0);
    expect(listeners['wiki-chat-stream-s1-done']?.length).toBe(0);
    expect(listeners['wiki-chat-stream-s1-error']?.length).toBe(0);
  });

  it('passes ownerToken to wikiChatStream and calls cancel on cleanup', async () => {
    mocks.wikiChatStream.mockResolvedValue({ streamId: 's1' });
    const request = {
      query: 'q',
      projectPath: '/p',
      llmBaseUrl: '',
      llmApiKey: '',
      llmModel: 'm',
      embedBaseUrl: '',
      embedApiKey: '',
      embedModel: 'm',
    };
    const { unmount } = renderHook(() => useWikiChatStream('s1', request));
    await act(async () => {});
    expect(wikiChatStream).toHaveBeenCalledWith(
      expect.objectContaining({
        streamId: 's1',
        ownerToken: expect.stringMatching(/^[a-f0-9-]{36}$/i),
      }),
    );
    const firstCall = mocks.wikiChatStream.mock.calls[0][0];
    const ownerToken = firstCall.ownerToken!;
    unmount();
    await act(async () => {});
    expect(cancelWikiChatStream).toHaveBeenCalledWith('s1', ownerToken);
  });

  it('StrictMode remount: first cleanup cancels with its own token, not the second mount', async () => {
    mocks.wikiChatStream.mockResolvedValue({ streamId: 's1' });
    const request = {
      query: 'q',
      projectPath: '/p',
      llmBaseUrl: '',
      llmApiKey: '',
      llmModel: 'm',
      embedBaseUrl: '',
      embedApiKey: '',
      embedModel: 'm',
    };
    // First mount (will be cleaned up by StrictMode)
    const { unmount: unmount1 } = renderHook(() => useWikiChatStream('s1', request));
    await act(async () => {});
    const firstToken = mocks.wikiChatStream.mock.calls[0][0].ownerToken!;
    // Unmount first (simulates StrictMode cleanup)
    unmount1();
    await act(async () => {});
    // Second mount (the one that stays)
    const { unmount: unmount2 } = renderHook(() => useWikiChatStream('s1', request));
    await act(async () => {});
    const secondToken = mocks.wikiChatStream.mock.calls[1][0].ownerToken!;
    expect(firstToken).not.toBe(secondToken);
    // First cancel with first token
    expect(cancelWikiChatStream).toHaveBeenNthCalledWith(1, 's1', firstToken);
    // Second cancel with second token (when unmount2 is called)
    unmount2();
    await act(async () => {});
    expect(cancelWikiChatStream).toHaveBeenNthCalledWith(2, 's1', secondToken);
  });
});
