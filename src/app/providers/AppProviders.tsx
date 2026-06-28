import { type ReactNode } from 'react';

import { I18nProvider } from '../../shared/lib/i18n';
import { ThemeErrorBoundary } from '../../widgets/theme/ErrorBoundary';
import { ThemeProvider as P3ThemeProvider } from '../../widgets/theme/ThemeProvider';

import { ErrorBoundary } from './ErrorBoundary';
import { QueryClientProvider } from './QueryClientProvider';
import { ThemeProvider } from './ThemeProvider';
import { ToastProvider } from './ToastProvider';

interface AppProvidersProps {
  children: ReactNode;
}

/**
 * 顶层 Provider 组合。按从外到内的顺序：
 *   ErrorBoundary > Theme(M0) > I18n > ThemeErrorBoundary(P3) > Theme(P3) > QueryClient > (children) > Toast
 *
 * - ErrorBoundary 在最外，任何子树的未捕获错误都能兜住
 * - M0 Theme 紧跟其后，I18n/QueryClient/Toast 都需要 theme 值
 * - I18n 在 QueryClient 之前，确保所有子组件都能使用 t()
 * - P3 ThemeErrorBoundary 包住 P3 ThemeProvider，主题系统内部崩溃不影响全应用
 * - P3 ThemeProvider 必须放在 I18nProvider 内部（它用 useI18n）
 * - QueryClient 是 server-state cache 根
 * - Toast 渲染在子树的兄弟位置（不嵌套），让 toast 浮在路由层之上
 */
export function AppProviders({ children }: AppProvidersProps) {
  return (
    <ErrorBoundary>
      <ThemeProvider>
        <I18nProvider>
          <ThemeErrorBoundary>
            <P3ThemeProvider>
              <QueryClientProvider>
                {children}
                <ToastProvider />
              </QueryClientProvider>
            </P3ThemeProvider>
          </ThemeErrorBoundary>
        </I18nProvider>
      </ThemeProvider>
    </ErrorBoundary>
  );
}
