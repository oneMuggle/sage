/**
 * UX-IA R1 A1：命令面板的跨组件打开信号。
 *
 * 命令面板的 open 状态由 App 持有；侧栏「搜索」按钮等非键盘入口通过派发该
 * window 事件请求打开，与 Ctrl/Cmd+K 共用同一面板（全局搜索在其中）。
 */
export const OPEN_COMMAND_PALETTE_EVENT = 'sage:command-palette:open';

export function requestOpenCommandPalette(): void {
  window.dispatchEvent(new Event(OPEN_COMMAND_PALETTE_EVENT));
}
