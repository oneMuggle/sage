/**
 * useCountdown — 重试等待倒计时。
 *
 * 2026-10-20: LLM 重试可视化。后端在每次重试前推送 delay（退避秒数），
 * 前端需要显示剩余等待时间。initialSeconds 变化时重置（新一轮重试事件到达）。
 * 到 0 后停止 ticking，避免无意义的 re-render。
 */
import { useEffect, useState } from 'react';

/**
 * 把外部传入的秒数规整为非负整数。
 * 非有限值（NaN / Infinity / undefined）一律视为 0，避免倒计时显示 NaN。
 */
function normalizeSeconds(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.ceil(value));
}

/**
 * @param initialSeconds 倒计时起始秒数（来自 RetryInfo.delay）
 * @param resetKey 额外的重置信号。连续两次重试 delay 相同时（如都退避 2 秒），
 *   仅靠 initialSeconds 无法感知新一轮，调用方传 attempt 等单调递增量来触发重置。
 * @returns 当前剩余秒数（整数，>= 0）
 */
export function useCountdown(initialSeconds: number, resetKey?: string | number): number {
  const [remaining, setRemaining] = useState(() => normalizeSeconds(initialSeconds));

  useEffect(() => {
    const start = normalizeSeconds(initialSeconds);
    setRemaining(start);
    if (start <= 0) return;

    const timer = setInterval(() => {
      setRemaining((prev) => {
        if (prev <= 1) {
          clearInterval(timer);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, [initialSeconds, resetKey]);

  return remaining;
}
