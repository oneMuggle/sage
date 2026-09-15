import { settingsClient, type PreferenceKey } from '../../shared/api/settingsClient';

import { normalizeFontSettings, type FontSettings } from './fontOptions';

export const FONT_STORAGE_KEY = 'sage-font-settings';

const PREFERENCE_KEYS = {
  fontUi: 'font_ui',
  fontCode: 'font_code',
  fontSizeUi: 'font_size_ui',
  fontSizeCode: 'font_size_code',
} as const satisfies Record<keyof FontSettings, PreferenceKey>;

// Two independent queues with distinct responsibilities:
//
// 1. `loadQueue` serializes the *load-vs-save ordering* — `loadFontSettings`
//    enters via this queue so the initial load (or a pending recovery save)
//    completes before the Provider's first user-initiated save can start.
//    `saveFontSettings` does NOT enter this queue; it is the caller's
//    responsibility (the Provider enqueues it) to keep load/save ordered.
//
// 2. `remoteQueue` serializes actual IPC writes. Both user-initiated saves
//    and pending-recovery saves flow through it, so a slow recovery cannot
//    overwrite a newer user value on the wire.
//
// Local cache writes happen synchronously BEFORE any async work, so a
// crash during a remote write never loses the latest user edit.
let loadQueue: Promise<unknown> = Promise.resolve();
function enqueueLoad<T>(operation: () => Promise<T>): Promise<T> {
  const result = loadQueue.then(operation);
  loadQueue = result.catch(() => undefined);
  return result;
}

let remoteQueue: Promise<unknown> = Promise.resolve();
function enqueueRemote<T>(operation: () => Promise<T>): Promise<T> {
  const result = remoteQueue.then(operation);
  remoteQueue = result.catch(() => undefined);
  return result;
}

// Version counter: each save bumps it synchronously at call time. Remote
// writes check it before clearing the pending flag so an older completed
// write never clobbers the pending state of a newer, still-pending save.
let cacheVersion = 0;

function loadLocal(): { settings: FontSettings; pending: boolean } {
  try {
    const cached: unknown = JSON.parse(localStorage.getItem(FONT_STORAGE_KEY) ?? 'null');
    return {
      settings: normalizeFontSettings(cached),
      pending:
        cached !== null &&
        typeof cached === 'object' &&
        'pending' in cached &&
        cached.pending === true,
    };
  } catch {
    // 损坏缓存或隐私模式：使用默认值。
    return { settings: normalizeFontSettings(null), pending: false };
  }
}

function cacheSettings(settings: FontSettings, pending = false): void {
  try {
    localStorage.setItem(
      FONT_STORAGE_KEY,
      JSON.stringify(pending ? { ...settings, pending: true } : settings),
    );
  } catch {
    // 缓存是尽力而为；存储不可用时仍可读写远端偏好。
  }
}

// Core remote-write logic, not queued by itself — callers wrap it with
// `enqueueRemote`. `thisVersion` is compared against `cacheVersion` when
// the remote write completes: only the LATEST save clears the pending
// flag, so a newer in-flight save's pending=true cache is never clobbered
// by an older completed save.
async function doSave(
  settings: FontSettings,
  thisVersion: number,
): Promise<void> {
  const results = await Promise.allSettled(
    Object.entries(PREFERENCE_KEYS).map(([field, key]) =>
      settingsClient.setPreferenceStrict(
        key,
        String(settings[field as keyof FontSettings]),
        'ui',
      ),
    ),
  );
  const failure = results.find((result) => result.status === 'rejected');
  if (failure?.status === 'rejected') throw failure.reason;

  if (thisVersion === cacheVersion) {
    cacheSettings(settings, false);
  }
}

export async function loadFontSettings(): Promise<FontSettings> {
  return enqueueLoad(async () => {
    const { settings: local, pending } = loadLocal();
    if (pending) {
      // Retry the pending snapshot via `remoteQueue`. This serializes the
      // recovery write with any concurrent user-initiated save — without
      // the queue, a slow recovery could land after a newer user save and
      // overwrite it on the wire. Errors are swallowed: on failure the
      // cache keeps `pending: true` so the next load retries.
      const recoveryVersion = ++cacheVersion;
      await enqueueRemote(() => doSave(local, recoveryVersion)).catch(() => undefined);
      return local;
    }
    const values = await Promise.all(
      Object.entries(PREFERENCE_KEYS).map(async ([field, key]) => {
        // settingsClient 正常情况下以 null 表示失败，也防御替代客户端抛错。
        const remote = await settingsClient.getPreference(key).catch(() => null);
        return [field, remote ?? local[field as keyof FontSettings]];
      }),
    );
    const settings = normalizeFontSettings(Object.fromEntries(values));
    cacheSettings(settings);
    return settings;
  });
}

export async function saveFontSettings(value: unknown): Promise<void> {
  const settings = normalizeFontSettings(value);

  // Synchronous: bump version + write cache with pending=true.
  // The version counter must be bumped HERE (at call time), not inside
  // the queued doSave, so that two saves fired in the same tick get
  // distinct versions and the older one's completion never clears the
  // newer one's pending flag.
  const thisVersion = ++cacheVersion;
  cacheSettings(settings, true);

  // Only the remote write is serialized through the remote queue.
  await enqueueRemote(() => doSave(settings, thisVersion));
}
