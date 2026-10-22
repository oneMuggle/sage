import {
  QueryClient,
  QueryClientProvider as TanstackQueryClientProvider,
} from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';

interface QueryClientProviderProps {
  children: ReactNode;
}

/**
 * TanStack Query Provider 封装。在 useState 中创建 QueryClient 实例，
 * 避免 React StrictMode 双调时 client 被重建/重置。
 *
 * 默认 config：
 * - staleTime 30s：避免重复请求
 * - retry 1：失败时重试 1 次
 * - refetchOnWindowFocus false：桌面端不必要
 *
 * 注：本 Provider 是 B15-19 骨架；既有 useChat / useKnowledge 等数据获取
 * 仍走旧的 useEffect+fetch 模式。迁移到 useQuery 是后续专项。
 */
export function QueryClientProvider({ children }: QueryClientProviderProps) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            retry: 1,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  return <TanstackQueryClientProvider client={client}>{children}</TanstackQueryClientProvider>;
}
// eslint-disable-next-line react-refresh/only-export-components
export function formatQueryClientConfigSummary(
  staleTimeMs = 30_000,
  retry = 1,
  refetchOnWindowFocus = false,
): string {
  const safeStale = Math.max(0, Math.trunc(staleTimeMs));
  const safeRetry = Math.max(0, Math.trunc(retry));
  return `staleTimeMs=${safeStale} · retry=${safeRetry} · refetchOnWindowFocus=${Boolean(refetchOnWindowFocus)}`;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatQueryClientConfigJson(
  staleTimeMs = 30_000,
  retry = 1,
  refetchOnWindowFocus = false,
): string {
  return JSON.stringify({
    staleTimeMs: Math.max(0, Math.trunc(staleTimeMs)),
    retry: Math.max(0, Math.trunc(retry)),
    refetchOnWindowFocus: Boolean(refetchOnWindowFocus),
  });
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditQueryClientProviderGovernance(
  state: {
    staleTimeMs?: number;
    retryCount?: number;
  } = {},
): {
  module: 'src/app/providers/QueryClientProvider.tsx';
  phase: 'P151';
  staleTimeMs: number;
  retryCount: number;
  healthy: boolean;
} {
  const staleTimeMs =
    typeof state.staleTimeMs === 'number' && Number.isFinite(state.staleTimeMs)
      ? Math.max(0, Math.round(state.staleTimeMs))
      : 60000;
  const retryCount =
    typeof state.retryCount === 'number' && Number.isFinite(state.retryCount)
      ? Math.max(0, Math.min(10, Math.trunc(state.retryCount)))
      : 1;
  return {
    module: 'src/app/providers/QueryClientProvider.tsx',
    phase: 'P151',
    staleTimeMs,
    retryCount,
    healthy: staleTimeMs >= 1000 && retryCount >= 0 && retryCount <= 10,
  };
}
