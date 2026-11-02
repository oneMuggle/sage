// src/widgets/chat/progress/progressFormat.ts
// 进度面板各视图（StatusBar / CurrentTaskFocus / TaskTreeSection /
// TaskDetailView）共用的数值格式化，避免同一指标在不同视图里口径不一。

/** token 消耗：≥1k 显 k（1 位小数去尾 0），其余显整数。 */
export const formatTokens = (tokens: number): string =>
  tokens >= 1000 ? `${(tokens / 1000).toFixed(1).replace(/\.0$/, '')}k tokens` : `${tokens} tokens`;

/** 终态时长：<1s 显 ms，其余显秒（1 位小数）。 */
export const formatDuration = (ms: number): string =>
  ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1).replace(/\.0$/, '')}s`;

/** 运行中耗时：<60s 显秒、<1h 显分秒、否则时分。 */
export const formatElapsed = (ms: number): string => {
  const totalSec = Math.max(0, Math.floor(ms / 1000));
  if (totalSec < 60) return `${totalSec}s`;
  const hh = Math.floor(totalSec / 3600);
  const mm = Math.floor((totalSec % 3600) / 60);
  const ss = totalSec % 60;
  if (hh > 0) return `${hh}h${String(mm).padStart(2, '0')}m`;
  return `${mm}m${String(ss).padStart(2, '0')}s`;
};

/** 墙钟时刻 → HH:MM:SS（事件时间线用）。 */
export const formatClockTime = (ts: number): string =>
  new Date(ts).toLocaleTimeString('zh-CN', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
