import { useEffect, useState, useCallback } from 'react';

import { listen, type UnlistenFn } from '../../shared/api/desktopEvent';
import {
  wikiChatStream,
  cancelWikiChatStream,
  type WikiChatStreamRequest,
} from '../../shared/api-client/wiki';
import type { WikiCitation } from '../../shared/types/wiki';

export interface ChatStreamState {
  answer: string;
  citations: WikiCitation[];
  sources: WikiCitation[];
  streaming: boolean;
  completed: boolean;
  error: string | null;
}

const emptyState: ChatStreamState = {
  answer: '',
  citations: [],
  sources: [],
  streaming: false,
  completed: false,
  error: null,
};

export function useWikiChatStream(streamId: string | null, request?: WikiChatStreamRequest) {
  const [state, setState] = useState<ChatStreamState>(emptyState);

  useEffect(() => {
    if (!streamId) {
      setState(emptyState);
      return;
    }
    setState({ ...emptyState, streaming: true });
    let disposed = false;
    const unlisteners: UnlistenFn[] = [];
    const subscriptions: Promise<void>[] = [];
    const ownerToken = crypto.randomUUID();
    const register = (subscription: Promise<UnlistenFn>) => {
      subscriptions.push(
        subscription
          .then((fn) => {
            if (disposed) fn();
            else unlisteners.push(fn);
          })
          .catch((error: unknown) => {
            if (!disposed) {
              setState((s) => ({ ...s, streaming: false, completed: true, error: String(error) }));
              disposed = true;
              unlisteners.forEach((unlisten) => unlisten());
            }
          }),
      );
    };
    register(
      listen<string>(
        `wiki-chat-stream-${streamId}-chunk`,
        (event) => {
          if (!disposed)
            setState((s) => (s.completed ? s : { ...s, answer: s.answer + event.payload }));
        },
        { streamId },
      ),
    );
    register(
      listen<{ citations: WikiCitation[]; sources: WikiCitation[] }>(
        `wiki-chat-stream-${streamId}-done`,
        (event) => {
          if (!disposed)
            setState((s) => ({
              ...s,
              streaming: false,
              completed: true,
              citations: event.payload.citations,
              sources: event.payload.sources ?? [],
            }));
        },
        { streamId },
      ),
    );
    register(
      listen<{ code?: string; message?: string; error?: string } | string>(
        `wiki-chat-stream-${streamId}-error`,
        (event) => {
          const payload = event.payload;
          const error =
            typeof payload === 'string'
              ? payload
              : (payload?.message ?? payload?.error ?? 'Wiki 聊天失败');
          if (!disposed) setState((s) => ({ ...s, streaming: false, completed: true, error }));
        },
        { streamId },
      ),
    );
    void Promise.all(subscriptions).then(async () => {
      if (disposed || !request) return;
      try {
        await wikiChatStream({ ...request, streamId, ownerToken });
      } catch (error) {
        if (!disposed)
          setState((s) => ({
            ...s,
            streaming: false,
            completed: true,
            error: `查询失败：${String(error)}`,
          }));
      }
    });
    return () => {
      disposed = true;
      unlisteners.forEach((unlisten) => unlisten());
      void cancelWikiChatStream(streamId, ownerToken).catch(() => {});
    };
  }, [streamId, request]);

  const reset = useCallback(() => setState(emptyState), []);
  return { ...state, reset };
}
