/**
 * 后端分层就绪（Progressive Readiness）轮询。
 *
 * Supervisor 在 `/health/proof` 确认后端存活后，以 1s 间隔轮询
 * `/health/ready`（纯内存快照）并向渲染层广播逐模块 warmup 状态。
 * 有界：后端到达 L3（全部模块终态）或达到硬超时后停止轮询。
 *
 * 独立成模块便于单测（可指向任意本地 HTTP 地址）。
 */
import http from 'node:http';

export interface StartupStatusModule {
  state: 'pending' | 'warming' | 'ready' | 'degraded' | 'failed';
  layer: number;
  elapsed_ms: number | null;
  detail: Record<string, unknown> | null;
}

export interface StartupStatusSnapshot {
  status: 'warming' | 'ready' | 'degraded';
  phase: 'L0' | 'L1' | 'L2' | 'L3';
  boot_ms: number;
  modules: Record<string, StartupStatusModule>;
  warmup: { done: number; total: number };
}

/** GET 一个 `/health/ready` 快照；任何失败都返回 null（轮询可重试）。 */
export function fetchStartupStatus(
  url: string,
  timeoutMs = 1000,
  headers: Record<string, string> = {},
): Promise<StartupStatusSnapshot | null> {
  return new Promise((resolve) => {
    const req = http.get(url, { headers }, (res) => {
      let body = '';
      res.setEncoding('utf8');
      res.on('data', (chunk: string) => {
        body += chunk;
      });
      res.on('end', () => {
        if (res.statusCode !== 200) {
          resolve(null);
          return;
        }
        try {
          resolve(JSON.parse(body) as StartupStatusSnapshot);
        } catch {
          resolve(null);
        }
      });
      res.resume();
    });
    req.on('error', () => resolve(null));
    req.setTimeout(timeoutMs, () => {
      req.destroy();
      resolve(null);
    });
  });
}
