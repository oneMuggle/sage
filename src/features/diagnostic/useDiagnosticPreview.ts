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

/* v8 ignore start */
export function formatDiagnosticPreviewSummary(
  data?: Partial<PreviewResponse>,
  loading = false,
  hasError = false,
): string {
  const count = data?.count ?? 0;
  const version = data?.version?.trim() || 'unknown';
  return `count=${count} · version=${version} · loading=${loading} · error=${hasError}`;
}

export function formatDiagnosticPreviewJson(
  data?: Partial<PreviewResponse>,
  loading = false,
  hasError = false,
): string {
  return JSON.stringify({
    count: data?.count ?? 0,
    version: data?.version?.trim() || 'unknown',
    sampleCount: data?.sampleUrls?.length ?? 0,
    loading,
    hasError,
  });
}
/* v8 ignore stop */
