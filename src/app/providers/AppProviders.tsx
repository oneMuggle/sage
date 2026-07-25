import { type ReactNode } from 'react';

import { I18nProvider } from '../../shared/lib/i18n';
import { WorkspaceContextProvider } from '../../shared/lib/workspaceContext';

import { ErrorBoundary } from './ErrorBoundary';
import { QueryClientProvider } from './QueryClientProvider';
import { ThemeProvider } from './ThemeProvider';
import { ToastProvider } from './ToastProvider';

interface AppProvidersProps {
  children: ReactNode;
}

/**
 * 顶层 Provider 组合。按从外到内的顺序：
 *   ErrorBoundary > Theme > Workspace > I18n > QueryClient > (children) > Toast
 *
 * - ErrorBoundary 在最外，任何子树的未捕获错误都能兜住
 * - Theme 紧跟其后，QueryClient/Toast 都需要 theme 值
 * - Workspace 在 I18n 之前，让所有 UI 都能拿到当前 workspace path（M1-M2 默认 undefined，
 *   由后续 PR 把 Office.tsx 的 local useState 迁移到此处）
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
        <WorkspaceContextProvider value={undefined}>
          <I18nProvider>
            <QueryClientProvider>
              {children}
              <ToastProvider />
            </QueryClientProvider>
          </I18nProvider>
        </WorkspaceContextProvider>
      </ThemeProvider>
    </ErrorBoundary>
  );
}
