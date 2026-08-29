/**
 * Renderer-side IPC shim — invoke(cmd, args) → Electron main process → backend HTTP.
 *
 * 命名历史（2026-06-13）：
 * - 旧名 tauriInvoke（误导：实际委托 Electron，与 Tauri 无关）
 * - 新名 desktopInvoke（准确：桌面端 invoke，与 transport 解耦）
 *
 * 内部委托 `window.electronAPI.invoke`（preload.ts 通过 contextBridge 注入）
 * 主进程（electron/main.ts）再把 invoke 转成对 backend FastAPI 的 HTTP 调用
 *
 * §13.7 (2026-08-15): 错误规范化 —— main 进程 sage:invoke 用 new Error(msg)
 * 重包装，Error 自定义属性过不了 Electron 21 IPC，但 message（含 `→ <status>:`）
 * 可靠。renderer 唯一漏斗在此解析附加 status_code，全局所有调用点可读。
 *
 * Task 0 review round 1, finding #6: when the main process throws
 * BackendNotReadyError (cold-start gate), the renderer surfaces its message
 * verbatim instead of falling into the generic ECONNREFUSED branch.
 *
 * 测试通过 `vi.mock('@/shared/api/desktopInvoke')` 桩化，与底层 transport 解耦
 */
import type { ElectronAPI } from '../types/electron-api';

import { demoInvoke, isDemoMode } from './demoInterceptors';

/** 跨 IPC 的 HTTP 错误 —— status_code 由本漏斗解析附加。 */
export interface InvokeError extends Error {
  status_code?: number;
}

const STATUS_RE = /→ (\d+):/;

/** Marker that main process throws when backend isn't ready yet. */
const BACKEND_NOT_READY_MARKER = '后端服务尚未就绪';

export async function invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  // 演示模式 (2026-08-27): 白名单通道直接返回合成数据, 不走 IPC/后端。
  // get_settings / set_settings 不在注册表内, 始终走真实通道。
  // 未命中通道 fallthrough 到原路径 (演示模式下后端已关, 由各 client 既有降级消化)。
  if (isDemoMode()) {
    const demo = demoInvoke(cmd, args ?? {});
    if (!demo.hit) {
      throw new Error('演示模式不支持该后端操作');
    }
    await new Promise((resolve) => setTimeout(resolve, 120 + Math.random() * 140));
    return demo.value as T;
  }
  const api: ElectronAPI | undefined =
    typeof window !== 'undefined' ? window.electronAPI : undefined;
  if (!api) {
    throw new Error(
      'electronAPI not available — preload script not loaded. ' +
        'If running outside Electron (e.g. plain browser), this is expected.',
    );
  }
  try {
    return await api.invoke<T>(cmd, args ?? {});
  } catch (err) {
    if (err instanceof Error && (err as InvokeError).status_code == null) {
      const m = err.message.match(STATUS_RE);
      if (m) (err as InvokeError).status_code = Number(m[1]);
    }
    const raw = err instanceof Error ? err.message : String(err);
    // Task 0 review round 1: BackendNotReadyError takes precedence over the
    // generic ECONNREFUSED check — otherwise the latter would re-wrap the
    // readiness-gate message with a different Chinese text and the
    // BackendStatusBanner couldn't tell them apart.
    if (raw.includes(BACKEND_NOT_READY_MARKER)) {
      throw new Error(raw);
    }
    // PR-B (2026-08-18): 把后端断开的 ECONNREFUSED / fetch failed / network error
    // 翻译成中文友好提示，让上层（React Query / UI）拿到稳定的 Error 而非
    // 裸英文 system error。其他错误（验证失败、HTTP 4xx 等）原样抛出，保持
    // status_code 属性与原始 message（含 /validation/ 等可读标记）。
    const isBackendDown =
      raw.includes('ECONNREFUSED') || raw.includes('fetch failed') || raw.includes('network error');
    if (isBackendDown) {
      throw new Error('后端服务未启动或已断开，请稍候自动重连或重启 Sage');
    }
    throw err instanceof Error ? err : new Error(raw);
  }
}
