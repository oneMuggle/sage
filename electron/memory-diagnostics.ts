/**
 * Memory Diagnostics Registry — Electron main process
 *
 * 2026-09-22 (ZCode-inspired optimization): 参考 ZCode 的 MemoryDiagnosticsRegistry，
 * 为 Sage Electron 主进程实现内存诊断系统。
 *
 * 功能：
 * 1. 60 秒采样 JS heap 使用量 + 业务计数器
 * 2. 门控写入（只在数据变化时写日志，避免日志膨胀）
 * 3. 通过 IPC 暴露到渲染进程，可在设置页查看
 *
 * 用法：
 *   import { getMemoryDiagnostics, registerCounter } from './memory-diagnostics';
 *   const diagnostics = getMemoryDiagnostics();
 *   diagnostics.startSampling();  // 启动 60s 采样循环
 *   diagnostics.registerCounter('active-sessions', () => sessionStore.size);
 */

import { logger } from './logger';

interface MemorySnapshot {
  timestamp: number;
  heapUsed: number;
  heapTotal: number;
  rss: number;
  external: number;
  counters: Record<string, number>;
}

class MemoryDiagnosticsRegistry {
  private counters = new Map<string, () => number>();
  private history: MemorySnapshot[] = [];
  private lastWriteHash = '';
  private samplingInterval: NodeJS.Timeout | null = null;
  private maxHistorySize = 60; // 保留最近 60 个样本（1 小时）

  /**
   * 注册业务计数器
   * @param name 计数器名称（如 'active-sessions', 'open-streams'）
   * @param getter 返回当前值的函数
   */
  registerCounter(name: string, getter: () => number): void {
    this.counters.set(name, getter);
    logger.info('memory-diagnostics: registered counter', { name });
  }

  /**
   * 采集一次内存快照
   */
  sample(): MemorySnapshot {
    const mem = process.memoryUsage();
    const counters: Record<string, number> = {};

    for (const [name, getter] of Array.from(this.counters.entries())) {
      try {
        counters[name] = getter();
      } catch (err) {
        logger.warn('memory-diagnostics: counter getter failed', { name, error: String(err) });
        counters[name] = -1; // 标记为失败
      }
    }

    return {
      timestamp: Date.now(),
      heapUsed: mem.heapUsed,
      heapTotal: mem.heapTotal,
      rss: mem.rss,
      external: mem.external,
      counters,
    };
  }

  /**
   * 门控写入：只在数据变化时写日志
   * 避免 60s 采样循环产生大量重复日志
   */
  private logIfChanged(snapshot: MemorySnapshot): void {
    const hash = this.computeHash(snapshot);
    if (hash !== this.lastWriteHash) {
      this.lastWriteHash = hash;
      logger.info('memory-diagnostics: snapshot', {
        heapUsedMB: Math.round(snapshot.heapUsed / 1024 / 1024),
        heapTotalMB: Math.round(snapshot.heapTotal / 1024 / 1024),
        rssMB: Math.round(snapshot.rss / 1024 / 1024),
        externalMB: Math.round(snapshot.external / 1024 / 1024),
        counters: snapshot.counters,
      });
    }
  }

  /**
   * 计算快照的哈希值（用于门控写入）
   * 只比较关键指标，忽略 timestamp
   */
  private computeHash(snapshot: MemorySnapshot): string {
    const key = [
      Math.round(snapshot.heapUsed / 1024 / 1024), // 按 MB 粒度比较
      Math.round(snapshot.rss / 1024 / 1024),
      JSON.stringify(snapshot.counters),
    ].join(':');
    return key;
  }

  /**
   * 启动 60 秒采样循环
   */
  startSampling(intervalMs = 60_000): void {
    if (this.samplingInterval !== null) {
      logger.warn('memory-diagnostics: sampling already started');
      return;
    }

    logger.info('memory-diagnostics: starting sampling loop', { intervalMs });

    // 立即采集一次
    const initial = this.sample();
    this.history.push(initial);
    this.logIfChanged(initial);

    // 启动定时采样
    this.samplingInterval = setInterval(() => {
      const snapshot = this.sample();
      this.history.push(snapshot);

      // 限制历史大小
      if (this.history.length > this.maxHistorySize) {
        this.history.shift();
      }

      this.logIfChanged(snapshot);
    }, intervalMs);
  }

  /**
   * 停止采样循环
   */
  stopSampling(): void {
    if (this.samplingInterval !== null) {
      clearInterval(this.samplingInterval);
      this.samplingInterval = null;
      logger.info('memory-diagnostics: sampling stopped');
    }
  }

  /**
   * 获取最近的采样历史
   */
  getHistory(): MemorySnapshot[] {
    return [...this.history];
  }

  /**
   * 获取最新快照
   */
  getLatest(): MemorySnapshot | null {
    return this.history.length > 0 ? this.history[this.history.length - 1] : null;
  }

  /**
   * 序列化为 JSON（用于 IPC 响应）
   */
  toJSON(): object {
    const latest = this.getLatest();
    return {
      enabled: this.samplingInterval !== null,
      historySize: this.history.length,
      latest: latest
        ? {
            timestamp: latest.timestamp,
            heapUsedMB: Math.round(latest.heapUsed / 1024 / 1024),
            heapTotalMB: Math.round(latest.heapTotal / 1024 / 1024),
            rssMB: Math.round(latest.rss / 1024 / 1024),
            externalMB: Math.round(latest.external / 1024 / 1024),
            counters: latest.counters,
          }
        : null,
    };
  }
}

// 全局单例
let registry: MemoryDiagnosticsRegistry | null = null;

/**
 * 获取全局内存诊断注册表
 */
export function getMemoryDiagnostics(): MemoryDiagnosticsRegistry {
  if (registry === null) {
    registry = new MemoryDiagnosticsRegistry();
  }
  return registry;
}

/**
 * 便捷函数：注册业务计数器
 */
export function registerCounter(name: string, getter: () => number): void {
  getMemoryDiagnostics().registerCounter(name, getter);
}

/**
 * 便捷函数：启动采样
 */
export function startMemorySampling(intervalMs?: number): void {
  getMemoryDiagnostics().startSampling(intervalMs);
}

/**
 * 便捷函数：停止采样
 */
export function stopMemorySampling(): void {
  getMemoryDiagnostics().stopSampling();
}
