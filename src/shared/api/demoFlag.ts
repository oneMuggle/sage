/**
 * 演示模式开关判定 (R2 从 demoInterceptors 下沉):
 *
 * isDemoMode() 被所有 api client 在请求路径上同步调用, 必须零重依赖 ——
 * 此前它住在 demoInterceptors 里, 导致 1800+ 行 demo 假数据被静态拖进
 * 主 chunk。下沉到本模块后, 各 client 只 import 这个轻模块; demo 数据
 * 模块 (demoInterceptors / demoChatScript) 改为 demo 分支内 dynamic
 * import, 仅演示模式按需加载。
 *
 * 2026-08-27 修复保留: 优先读 main 进程经 webPreferences.additionalArguments
 * → preload argv 同步注入的标志。首屏请求 (loadSessions / loadMessages 等)
 * 早于 loadSettings 完成, 只读 store 会竞态漏拦截 → 请求打到已跳过的后端
 * 报 ECONNREFUSED。store 兜底保留, 覆盖设置页即时切换的场景。
 */
import { useSettingsStore } from '../../features/manage-settings/settingsStore';

import { getDemoModeOverride } from './demoRuntime';

export function isDemoMode(): boolean {
  const override = getDemoModeOverride();
  if (override !== undefined) return override;
  if (typeof window !== 'undefined' && window.electronAPI?.demoMode === true) return true;
  return useSettingsStore.getState().settings.demoMode === true;
}
