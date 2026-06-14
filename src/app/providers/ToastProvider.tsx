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
