/**
 * 后端就绪信号 —— 集中订阅 backend:ready / backend:reconnected 事件。
 *
 * 背景：主进程就绪队列（PR #2980 / electron/backendReadyQueue.ts）已覆盖冷启动
 * 期间的常规请求；但仍有边界场景（队列溢出、退出期 rejectAll、demo 模式、
 * 未来生命周期竞争窗口）会让首屏一次性拉取失败。本模块为渲染层兜底：组件
 * 订阅后在 ready/reconnected 事件触发时执行重放，无需依赖固定定时轮询。
 *
 * 设计要点：
 *   - 单例：所有调用方共享同一份 listener，避免重复订阅 IPC。
 *   - 懒安装：首次注册时才调用 electronAPI.listen；web/test 环境下 electronAPI
 *     缺失时静默降级（handler 永远不会触发）。
 *   - 不广播启动期的 ready：只在已订阅后发生的 ready/reconnected 事件触发。
 *     组件若在 ready 之后才订阅，不会"补发"——避免重复拉取已成功的数据。
 */

import * as React from 'react';

type Handler = () => void;

const handlers = new Set<Handler>();
let installed = false;

function ensureInstalled(): void {
  if (installed) return;
  const api = typeof window !== 'undefined' ? window.electronAPI : undefined;
  if (!api || typeof api.listen !== 'function') return;
  installed = true;

  const broadcast = (): void => {
    handlers.forEach((fn) => {
      try {
        fn();
      } catch (err) {
        // 一个订阅的异常不应阻塞其他订阅。
        console.error('[backendReadySignal] handler threw:', err);
      }
    });
  };

  void api.listen('backend:ready', broadcast);
  void api.listen('backend:reconnected', broadcast);
}

/**
 * 注册一个"后端就绪"回调；返回取消订阅函数。
 * 非 React 场景（store、非组件模块）用此 API。React 组件优先使用 `useBackendReadyTick`。
 */
export function onBackendReady(handler: Handler): () => void {
  ensureInstalled();
  handlers.add(handler);
  return () => {
    handlers.delete(handler);
  };
}

/**
 * React hook：返回一个单调递增的计数，每次 backend:ready / backend:reconnected
 * 事件触发时 +1。组件把它加入 useEffect deps 即可自动重放启动期拉取。
 *
 * 用法示例：
 *   const tick = useBackendReadyTick();
 *   useEffect(() => { void load(); }, [load, tick]);
 */
export function useBackendReadyTick(): number {
  const [tick, setTick] = React.useState(0);
  React.useEffect(() => onBackendReady(() => setTick((t) => t + 1)), []);
  return tick;
}
