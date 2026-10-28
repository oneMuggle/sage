/**
 * 闲时延迟执行 — 前端活动上报
 *
 * 监听用户交互事件（mousemove / keydown / click），
 * 节流后通过 backendRequest 上报到后端 IdleDetector。
 *
 * 使用方式：在 App 或 Layout 组件中调用 initIdleReporter()。
 */

import { backendRequest } from '../../shared/api/backendRequest';

const REPORT_INTERVAL_MS = 30_000; // 最多 30 秒上报一次
let lastReportTime = 0;
let initialized = false;
let pendingReport = false;
let timerId: ReturnType<typeof setTimeout> | null = null;

function reportActivity(): void {
  const now = Date.now();
  if (now - lastReportTime < REPORT_INTERVAL_MS) {
    // 节流中：标记有待上报，等下次
    pendingReport = true;
    return;
  }

  lastReportTime = now;
  pendingReport = false;

  backendRequest({
    method: 'POST',
    path: '/api/v1/idle/activity',
    body: { source: 'web' },
  }).catch(() => {
    // 静默失败 — 不影响用户体验
  });
}

function scheduleFlush(): void {
  if (timerId !== null) return;
  timerId = setTimeout(() => {
    timerId = null;
    if (pendingReport) {
      reportActivity();
    }
  }, REPORT_INTERVAL_MS);
}

function onUserActivity(): void {
  reportActivity();
  scheduleFlush();
}

/**
 * 初始化空闲活动上报器。
 * 应在 App 级别调用一次。
 * 重复调用是安全的（幂等）。
 */
export function initIdleReporter(): void {
  if (initialized) return;
  if (typeof window === 'undefined') return;

  initialized = true;

  // 监听用户活动事件（passive 以提升滚动性能）
  window.addEventListener('mousemove', onUserActivity, { passive: true });
  window.addEventListener('keydown', onUserActivity, { passive: true });
  window.addEventListener('click', onUserActivity, { passive: true });
  window.addEventListener('scroll', onUserActivity, { passive: true });
  window.addEventListener('touchstart', onUserActivity, { passive: true });

  // 初始上报一次（启动时视为"刚活跃"）
  reportActivity();
}

/**
 * 获取空闲状态（供 UI 显示）
 */
export async function fetchIdleStatus(): Promise<{
  idle_level: 'none' | 'short' | 'deep';
  idle_seconds: number;
  idle_minutes: number;
}> {
  return backendRequest({
    method: 'GET',
    path: '/api/v1/idle/status',
  });
}
