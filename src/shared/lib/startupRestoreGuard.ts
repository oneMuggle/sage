/**
 * 启动恢复抑制标志。
 *
 * `AppStartupRestore` 会在异步读到"上次会话"后把 `/welcome` 回跳到 `/chat`。
 * 但读取可能耗时数秒（启动期 IPC 排队），期间用户可能已经明确选择
 * "新对话"或在欢迎页输入——此时回跳会把用户拽回旧会话并卸载欢迎页输入。
 *
 * 任何"用户主动创建/选择新对话"的入口在动作发生时调用
 * `suppressStartupSessionRestore()`，恢复逻辑完成时检查并放弃回跳。
 * 标志是进程级的：恢复只发生在启动阶段，之后无需复位。
 */
let suppressed = false;

export function suppressStartupSessionRestore(): void {
  suppressed = true;
}

export function isStartupSessionRestoreSuppressed(): boolean {
  return suppressed;
}

/** 测试辅助：重置标志。 */
export function resetStartupSessionRestoreGuardForTests(): void {
  suppressed = false;
}
