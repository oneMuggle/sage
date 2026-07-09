// useWikiIngest - 订阅 wiki-ingest-{id}-progress 事件,返回进度状态
import { useEffect, useState, useCallback } from 'react';

import { listen, type UnlistenFn } from '../../shared/api/desktopEvent';

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
    // PR-3 Task 4: pass `{ streamId }` so the unlisten closure forwards
    // the streamId to `sage:unlisten` — the main process aborts the
    // matching AbortController in `streamControllers`. Without this the
    // backend fetch keeps running until the backend finishes naturally,
    // leaking memory and CPU. See electron/main.ts::startWikiIngestStream.
    listen<IngestProgress>(
      eventName,
      (e) => {
        const p = e.payload;
        if (p.stage === 'completed') {
          setState({ progress: p, done: true, error: null });
        } else {
          setState({ progress: p, done: false, error: null });
        }
      },
      { streamId: ingestId },
    )
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
