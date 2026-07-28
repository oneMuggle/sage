import { type ReactNode } from 'react';

import { I18nProvider } from '../../shared/lib/i18n';

import { ErrorBoundary } from './ErrorBoundary';
import { QueryClientProvider } from './QueryClientProvider';
import { SessionWorkspaceProvider } from './SessionWorkspaceProvider';
import { ThemeProvider } from './ThemeProvider';
import { ToastProvider } from './ToastProvider';

interface AppProvidersProps {
  children: ReactNode;
}

/**
 * 顶层 Provider 组合。按从外到内的顺序：
 *   ErrorBoundary > Theme > SessionWorkspace > I18n > QueryClient > (children) > Toast
 *
 * - ErrorBoundary 在最外，任何子树的未捕获错误都能兜住
 * - Theme 紧跟其后，QueryClient/Toast 都需要 theme 值
 * - SessionWorkspace 在 I18n 之前，让所有 UI 都能拿到当前 session 的 workspace 状态。
 *   它是 renderer 端 workspace state 的唯一来源（Task 5, 2026-07-26）：订阅
 *   `useStore.currentSessionId` 并通过 `workspaceApi.get()` 拉取当前会话的 binding。
 * - I18n 在 QueryClient 之前，确保所有子组件都能使用 t()
 * - QueryClient 是 server-state cache 根
 * - Toast 渲染在子树的兄弟位置（不嵌套），让 toast 浮在路由层之上
 *
 * 注意：NavHistoryProvider 在 App.tsx 中，包裹在 BrowserRouter 内部，
 * 因为它需要使用 useLocation() hook。
 */
export function AppProviders({ children }: AppProvidersProps) {
  return (
    <ErrorBoundary>
      <ThemeProvider>
        <SessionWorkspaceProvider>
          <I18nProvider>
            <QueryClientProvider>
              {children}
              <ToastProvider />
            </QueryClientProvider>
          </I18nProvider>
        </SessionWorkspaceProvider>
      </ThemeProvider>
    </ErrorBoundary>
  );
}
