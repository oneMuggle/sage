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
