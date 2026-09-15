/**
 * useElapsedSeconds — busy 期间的已耗时秒表。
 *
 * P2 (UI 优化方案 2026-09-13): 后端暂无百分比进度的长任务（office 生成/
 * 导出等），用「阶段文案 + 已耗时」替代纯 disabled 按钮的对青黄不接反馈
 * （对标 Cursor 的 searching/reading 阶段叙事）。active 变 false 自动归零。
 */
import { useEffect, useState } from 'react';

export function useElapsedSeconds(active: boolean): number {
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    if (!active) {
      setSeconds(0);
      return;
    }
    const startedAt = Date.now();
    setSeconds(0);
    const timer = setInterval(() => {
      setSeconds(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => clearInterval(timer);
  }, [active]);

  return seconds;
}
