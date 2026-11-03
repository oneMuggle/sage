/**
 * Module-level shared source for the global `chat_display_mode` preference.
 *
 * One lazy IPC read per app (not one per Message), reloaded whenever
 * `setPreferenceStrict('chat_display_mode', ...)` dispatches
 * `sage:setting-changed`. Consumers subscribe with `useSyncExternalStore`.
 */
import { settingsClient } from '../../../shared/api/settingsClient';

import { DEFAULT_DISPLAY_MODE, isValidDisplayMode, type DisplayMode } from './types';

let snapshot: DisplayMode = DEFAULT_DISPLAY_MODE;
let loaded = false;
let inflight: Promise<void> | null = null;
const listeners = new Set<() => void>();
let wired = false;

function emit(): void {
  for (const listener of listeners) listener();
}

async function load(): Promise<void> {
  if (inflight) return inflight;
  inflight = (async () => {
    try {
      const raw = await settingsClient.getPreferenceStrict('chat_display_mode');
      snapshot = isValidDisplayMode(raw) ? raw : DEFAULT_DISPLAY_MODE;
      loaded = true;
    } catch {
      // 后端未就绪时 IPC 会失败：保留当前快照，不置 loaded ——
      // 否则本会话永久停留在默认档位。下一个订阅者（新消息挂载 /
      // 页面重挂载）或 sage:setting-changed 事件会再次触发读取。
    } finally {
      inflight = null;
      emit();
    }
  })();
  return inflight;
}

function onSettingChanged(event: Event): void {
  const detail = (event as CustomEvent<{ key?: string }>).detail;
  if (detail?.key === 'chat_display_mode') void load();
}

function ensureWired(): void {
  if (wired || typeof window === 'undefined') return;
  wired = true;
  window.addEventListener('sage:setting-changed', onSettingChanged);
}

export function subscribeGlobalDisplayMode(listener: () => void): () => void {
  ensureWired();
  listeners.add(listener);
  if (!loaded && !inflight) void load();
  return () => {
    listeners.delete(listener);
  };
}

export function getGlobalDisplayModeSnapshot(): DisplayMode {
  return snapshot;
}

/** Test-only: restore module state between tests. */
export function __resetGlobalDisplayModeForTests(): void {
  snapshot = DEFAULT_DISPLAY_MODE;
  loaded = false;
  inflight = null;
  listeners.clear();
  if (wired) {
    window.removeEventListener('sage:setting-changed', onSettingChanged);
    wired = false;
  }
}
