import { useCallback, useEffect, useState } from 'react';

export interface PreviewResponse {
  count: number;
  oldestTs: string | null;
  newestTs: string | null;
  sampleUrls: string[];
  version: string;
}

export function useDiagnosticPreview() {
  const [data, setData] = useState<PreviewResponse | undefined>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | undefined>();

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(undefined);
    try {
      const resp = await window.electronAPI?.diagnostic?.preview();
      if (resp) {
        setData(resp);
      }
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { data, loading, error, refresh };
}
