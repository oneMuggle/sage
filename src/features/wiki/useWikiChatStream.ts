// useWikiChatStream - 订阅 wiki-chat-stream-{id} 事件,累积 chunk
import { useEffect, useState, useCallback } from 'react';

import { listen, type UnlistenFn } from '../../shared/api/desktopEvent';

export interface ChatStreamState {
  /** 累积的完整回答 */
  answer: string;
  /** 引用列表(stream 完成后填充) */
  citations: string[];
  /** 当前是否在流式 */
  streaming: boolean;
  /** 错误 */
  error: string | null;
}

export function useWikiChatStream(streamId: string | null) {
  const [state, setState] = useState<ChatStreamState>({
    answer: '',
    citations: [],
    streaming: false,
    error: null,
  });

  useEffect(() => {
    if (!streamId) return;
    setState({ answer: '', citations: [], streaming: true, error: null });
    const chunkEvent = `wiki-chat-stream-${streamId}-chunk`;
    const doneEvent = `wiki-chat-stream-${streamId}-done`;
    let unlistenChunk: UnlistenFn | null = null;
    let unlistenDone: UnlistenFn | null = null;

    listen<string>(chunkEvent, (e) => {
      setState((s) => ({ ...s, answer: s.answer + e.payload }));
    })
      .then((fn) => {
        unlistenChunk = fn;
      })
      .catch((e) => {
        setState((s) => ({ ...s, streaming: false, error: String(e) }));
      });

    listen<{ citations: string[] }>(doneEvent, (e) => {
      setState((s) => ({
        ...s,
        streaming: false,
        citations: e.payload.citations,
      }));
    })
      .then((fn) => {
        unlistenDone = fn;
      })
      .catch((e) => {
        setState((s) => ({ ...s, streaming: false, error: String(e) }));
      });

    return () => {
      if (unlistenChunk) unlistenChunk();
      if (unlistenDone) unlistenDone();
    };
  }, [streamId]);

  const reset = useCallback(() => {
    setState({ answer: '', citations: [], streaming: false, error: null });
  }, []);

  return { ...state, reset };
}
