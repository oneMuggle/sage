/**
 * 启动阶段埋点（渲染层）。
 *
 * 双通道：
 * - `performance.mark('sage:<stage>')` —— 渲染层 DevTools / 性能面板观测；
 * - Electron IPC `reportBootStage(stage)` —— 主进程 markBootStage 写入
 *   `diagnostics/last-run.json`，形成 window_shown → sessions_loaded 的
 *   完整启动瀑布。
 *
 * Web 模式 / 测试环境无 electronAPI 桥，静默跳过（不影响业务）。
 */
export type BootStage = 'sessions_loaded' | 'messages_loaded' | 'settings_loaded';

const emitted = new Set<BootStage>();

export function emitBootStage(stage: BootStage): void {
  if (typeof performance !== 'undefined' && typeof performance.mark === 'function') {
    try {
      performance.mark(`sage:${stage}`);
    } catch {
      // performance.mark 失败不影响业务
    }
  }
  try {
    window.electronAPI?.reportBootStage?.(stage);
  } catch {
    // 桥不可用时忽略
  }
}

/** 同一阶段每个进程只上报一次（重复视图挂载/重放不重复打点）。 */
export function markBootStageOnce(stage: BootStage): void {
  if (emitted.has(stage)) return;
  emitted.add(stage);
  emitBootStage(stage);
}

/** 测试辅助：重置去重状态。 */
export function resetBootStageMarksForTests(): void {
  emitted.clear();
}
