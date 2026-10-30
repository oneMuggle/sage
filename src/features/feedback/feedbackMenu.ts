// src/features/feedback/feedbackMenu.ts
//
// 帮助菜单「反馈问题...」→ 主进程 electron/menu.ts 发
// 'sage:event:open-feedback' → 渲染进程跳转 /feedback。
// 浏览器 / dev 环境无桥时 no-op。

import { listen, type UnlistenFn } from '../../shared/api/desktopEvent';

export function onOpenFeedbackRequest(
  handler: () => void,
): Promise<UnlistenFn | undefined> | undefined {
  const api = typeof window !== 'undefined' ? window.electronAPI : undefined;
  if (!api?.listen) return undefined;
  return listen<Record<string, never>>('open-feedback', () => handler()).catch(() => undefined);
}
