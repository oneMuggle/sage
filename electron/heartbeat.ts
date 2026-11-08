/**
 * heartbeat — renderer 心跳超时纯逻辑。
 *
 * renderer 每 15s 调一次 ``beat``；主进程定时调 ``check``。
 * 超时后只报告一次（``lost``），直到收到新的 beat 重新武装；这样避免
 * 每次 tick 都弹对话框。
 *
 * 不依赖 Electron，便于单测。
 */
export interface HeartbeatMonitor {
  /** 收到心跳（nowMs 可由调用方注入，便于测试）。 */
  beat(nowMs?: number): void;
  /** 返回 true = 本次检测到超时（只触发一次，直到下一次 beat）。 */
  check(nowMs?: number): boolean;
  /** 清空状态（例如窗口重建后）。 */
  reset(): void;
}

export interface HeartbeatOptions {
  /** 超时阈值（毫秒）。默认 60_000。 */
  timeoutMs?: number;
  /** 时间源，默认 Date.now。 */
  now?: () => number;
}

export function createHeartbeatMonitor(options: HeartbeatOptions = {}): HeartbeatMonitor {
  const timeoutMs = options.timeoutMs ?? 60_000;
  const now = options.now ?? (() => Date.now());
  let lastBeat: number | null = null;
  let fired = false;

  return {
    beat(nowMs?: number) {
      lastBeat = nowMs ?? now();
      fired = false;
    },
    check(nowMs?: number) {
      if (lastBeat === null) return false;
      if (fired) return false;
      const current = nowMs ?? now();
      if (current - lastBeat > timeoutMs) {
        fired = true;
        return true;
      }
      return false;
    },
    reset() {
      lastBeat = null;
      fired = false;
    },
  };
}
