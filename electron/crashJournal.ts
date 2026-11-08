/**
 * crashJournal — 结构化崩溃事件日志（NDJSON）。
 *
 * 与 ``sage-emergency.log`` 的分工：
 * - emergency log：最后兜底，纯文本，不依赖任何基础设施；
 * - crash journal：结构化字段，供救援工具分类/统计（理由、退出码、
 *   renderer pid、窗口年龄、兼容档位）。
 *
 * 不依赖 Electron；路径由调用方传入。
 */
import { appendFileSync, mkdirSync } from 'node:fs';
import { dirname } from 'node:path';

export interface CrashDetails {
  reason?: string;
  exitCode?: number | null;
  type?: string;
  rendererPid?: number;
  serviceName?: string;
  killed?: boolean;
}

export interface CrashContext {
  bootId: string;
  appVersion: string;
  electron: string;
  safeModeLevel: number;
  nowIso: string;
  windowAgeMs?: number;
  url?: string;
  route?: string;
  edr?: { products?: string[]; services?: string[] };
}

export interface CrashEvent {
  ts: string;
  bootId: string;
  appVersion: string;
  electron: string;
  event: string;
  reason: string;
  exitCode: number | null;
  type: string | null;
  rendererPid: number | null;
  serviceName: string | null;
  killed: boolean | null;
  windowAgeMs: number | null;
  url: string | null;
  route: string | null;
  safeModeLevel: number;
  edr: { products: string[]; services: string[] } | null;
}

export function buildCrashEvent(details: CrashDetails, context: CrashContext): CrashEvent {
  return {
    ts: context.nowIso,
    bootId: context.bootId,
    appVersion: context.appVersion,
    electron: context.electron,
    event: 'render-process-gone',
    reason: typeof details.reason === 'string' && details.reason ? details.reason : 'unknown',
    exitCode: typeof details.exitCode === 'number' ? details.exitCode : null,
    type: typeof details.type === 'string' ? details.type : null,
    rendererPid: typeof details.rendererPid === 'number' ? details.rendererPid : null,
    serviceName: typeof details.serviceName === 'string' ? details.serviceName : null,
    killed: typeof details.killed === 'boolean' ? details.killed : null,
    windowAgeMs: typeof context.windowAgeMs === 'number' ? context.windowAgeMs : null,
    url: typeof context.url === 'string' ? context.url : null,
    route: typeof context.route === 'string' ? context.route : null,
    safeModeLevel: context.safeModeLevel,
    edr: context.edr
      ? {
          products: Array.isArray(context.edr.products) ? context.edr.products : [],
          services: Array.isArray(context.edr.services) ? context.edr.services : [],
        }
      : null,
  };
}

export function appendCrashEvent(file: string, event: CrashEvent | Record<string, unknown>): void {
  try {
    mkdirSync(dirname(file), { recursive: true });
    appendFileSync(file, `${JSON.stringify(event)}\n`, 'utf-8');
  } catch {
    // last-resort：崩溃日志写不下去不能反过来影响进程
  }
}
