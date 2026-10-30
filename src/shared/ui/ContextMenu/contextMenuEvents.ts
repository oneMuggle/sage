/**
 * 右键菜单全局打开态 —— 供需要与菜单互斥的浮层（如划词引用按钮）订阅。
 *
 * 使用计数器而非布尔值，容忍多个 Trigger 在同一帧交接（关闭旧的、打开新的）。
 */
export const CONTEXT_MENU_OPEN_EVENT = 'sage:context-menu-open';

let openCount = 0;

export function markContextMenuOpen(open: boolean): void {
  const next = Math.max(0, openCount + (open ? 1 : -1));
  const wasOpen = openCount > 0;
  openCount = next;
  const isOpen = openCount > 0;
  if (wasOpen !== isOpen && isOpen && typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent(CONTEXT_MENU_OPEN_EVENT));
  }
}

export function isContextMenuOpen(): boolean {
  return openCount > 0;
}

/** 仅用于测试清理模块级状态。 */
export function resetContextMenuOpenCount(): void {
  openCount = 0;
}
