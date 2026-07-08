import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';

import { useWikiChatStream } from '../useWikiChatStream';

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
    Object.keys(listeners).forEach((k) => delete listeners[k]);
  });

  it('accumulates answer from chunk events and keeps streaming', async () => {
    const { result } = renderHook(
      ({ streamId }) => useWikiChatStream(streamId),
      { initialProps: { streamId: 's1' as string | null } },
    );
    await act(async () => {
      fire('wiki-chat-stream-s1-chunk', 'Hello');
      fire('wiki-chat-stream-s1-chunk', ' world');
    });
    expect(result.current.answer).toBe('Hello world');
    expect(result.current.streaming).toBe(true);
    expect(result.current.error).toBeNull();
  });

  it('sets streaming=false and citations on done event', async () => {
    const { result } = renderHook(
      ({ streamId }) => useWikiChatStream(streamId),
      { initialProps: { streamId: 's1' as string | null } },
    );
    await act(async () => {
      fire('wiki-chat-stream-s1-done', { citations: ['wiki/a.md', 'wiki/b.md'] });
    });
    expect(result.current.streaming).toBe(false);
    expect(result.current.citations).toEqual(['wiki/a.md', 'wiki/b.md']);
  });

  // Electron main relays 4 error payload shapes, but only 2 distinct runtime
  // shapes reach the renderer: an object `{ error: string }` (HTTP non-2xx,
  // non-AbortError catch, synthetic NDJSON-parse error) and a bare `string`
  // (backend error event data relayed verbatim). Both must normalize to
  // state.error: string.

  it('normalizes object-shape error payload { error } to state.error', async () => {
    const { result } = renderHook(
      ({ streamId }) => useWikiChatStream(streamId),
      { initialProps: { streamId: 's1' as string | null } },
    );
    await act(async () => {
      fire('wiki-chat-stream-s1-error', { error: 'LLM timeout' });
    });
    expect(result.current.error).toBe('LLM timeout');
    expect(result.current.streaming).toBe(false);
  });

  it('normalizes string error payload to state.error', async () => {
    const { result } = renderHook(
      ({ streamId }) => useWikiChatStream(streamId),
      { initialProps: { streamId: 's1' as string | null } },
    );
    await act(async () => {
      fire('wiki-chat-stream-s1-error', 'invalid NDJSON line');
    });
    expect(result.current.error).toBe('invalid NDJSON line');
    expect(result.current.streaming).toBe(false);
  });

  it('unlistens all events when streamId becomes null', async () => {
    const { rerender } = renderHook(
      ({ streamId }) => useWikiChatStream(streamId),
      { initialProps: { streamId: 's1' as string | null } },
    );
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
});
