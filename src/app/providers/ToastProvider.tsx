import { Toaster as SonnerToaster } from 'sonner';

import { useTheme } from './useTheme';

/**
 * 顶层 Toast 容器。订阅当前主题，让 toast 颜色随 light/dark 切换。
 *
 * 业务侧调用：import { toast } from 'sonner'; toast.success('保存成功')
 */
export function ToastProvider() {
  const { resolved } = useTheme();
  return (
    <SonnerToaster theme={resolved} position="top-right" richColors closeButton duration={4000} />
  );
}
// eslint-disable-next-line react-refresh/only-export-components
export function formatToastProviderSummary(
  theme: 'light' | 'dark' = 'light',
  durationMs = 4000,
): string {
  const safeDuration = Math.max(0, Math.trunc(durationMs));
  return `theme=${theme} · position=top-right · durationMs=${safeDuration}`;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatToastProviderJson(
  theme: 'light' | 'dark' = 'light',
  durationMs = 4000,
): string {
  return JSON.stringify({
    theme,
    position: 'top-right',
    richColors: true,
    closeButton: true,
    durationMs: Math.max(0, Math.trunc(durationMs)),
  });
}

