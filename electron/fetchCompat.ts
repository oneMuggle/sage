/**
 * 运行时 fetch 解析 (Electron 21 / Node 16 兼容)。
 *
 * Electron 21 主进程是 Node 16 —— 没有全局 fetch (Node 18 才内置)。
 * 测试跑在宿主 Node (>=18) 上, 全局 fetch 存在, 因此裸 `fetch` 在
 * vitest 里正常、打包运行时抛 `fetch is not defined`。主进程所有
 * 网络请求统一走这里: 调用时优先全局 fetch (测试可 vi.stubGlobal),
 * 缺失则回退 node-fetch。
 */
import nodeFetch from 'node-fetch';

export function fetchCompat(
  ...args: Parameters<typeof nodeFetch>
): ReturnType<typeof nodeFetch> {
  const runtimeFetch = (globalThis as unknown as { fetch?: typeof nodeFetch }).fetch ?? nodeFetch;
  return runtimeFetch(...args);
}
