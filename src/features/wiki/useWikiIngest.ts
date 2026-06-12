// useWikiIngest - 订阅 wiki-ingest-{id}-progress 事件,返回进度状态
import { useEffect, useState, useCallback } from 'react';

import { listen, type UnlistenFn } from '../../lib/tauriEvent';

export interface IngestProgress {
  stage: string;
  percent: number;
  message?: string | null;
}

export interface IngestState {
  progress: IngestProgress | null;
  done: boolean;
  error: string | null;
}

export function useWikiIngest(ingestId: string | null) {
  const [state, setState] = useState<IngestState>({
    progress: null,
    done: false,
    error: null,
  });

  useEffect(() => {
    if (!ingestId) return;
    const eventName = `wiki-ingest-${ingestId}-progress`;
    let unlisten: UnlistenFn | null = null;
    listen<IngestProgress>(eventName, (e) => {
      const p = e.payload;
      if (p.stage === 'completed') {
        setState({ progress: p, done: true, error: null });
      } else {
        setState({ progress: p, done: false, error: null });
      }
    })
      .then((fn) => {
        unlisten = fn;
      })
      .catch((e) => {
        setState({ progress: null, done: false, error: String(e) });
      });
    return () => {
      if (unlisten) unlisten();
    };
  }, [ingestId]);

  const reset = useCallback(() => {
    setState({ progress: null, done: false, error: null });
  }, []);

  return { ...state, reset };
}
