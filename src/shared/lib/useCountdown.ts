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

/**
 * useElapsed — 已等待秒数递增计时器。
 *
 * 2026-11-03: LLM 重试计时可见性。退避倒计时归零后，重试请求进入"在途"
 * 阶段（等上游响应），此时没有可倒数的目标，只知道已经等了多久。
 * 本 hook 提供从 resetKey 变化起单调递增的秒数，供横幅显示"本次已等待 Ns"。
 *
 * @param resetKey 重置信号（通常是 attempt 或 attempt+phase）。变化即归零重来。
 * @param tickMs  步进间隔（毫秒），默认 1000。
 * @returns 已等待秒数（整数，>= 0）
 */
export function useElapsed(resetKey?: string | number, tickMs = 1000): number {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    setElapsed(0);
    const timer = setInterval(() => {
      setElapsed((prev) => prev + 1);
    }, tickMs);
    return () => clearInterval(timer);
  }, [resetKey, tickMs]);

  return elapsed;
}

export function formatCountdownSummary(
  initialSeconds: number,
  remaining: number,
  resetKey?: string | number,
): string {
  const normalized = normalizeSeconds(initialSeconds);
  return `${remaining > 0 ? 'ticking' : 'done'} · ${remaining}/${normalized}s · key=${resetKey ?? 'none'}`;
}

export function formatCountdownJson(
  initialSeconds: number,
  remaining: number,
  resetKey?: string | number,
): string {
  return JSON.stringify(
    {
      initialSeconds: normalizeSeconds(initialSeconds),
      remaining,
      active: remaining > 0,
      resetKey: resetKey ?? null,
    },
    null,
    2,
  );
}

export function auditUseCountdownGovernance(): string {
  return JSON.stringify(
    {
      schema: 'sage.shared.lib.use_countdown.governance.v1',
      phase: 'P180',
      tickingSummary: formatCountdownSummary(5, 3, 1),
      doneSummary: formatCountdownSummary(5, 0, 1),
    },
    null,
    2,
  );
}
