/**
 * compatProfile — 兼容档位（安全模式）纯逻辑。
 *
 * 与 ``backend/services/rescue/compat_profile.py`` 保持同一 schema 与档位表；
 * 机器本地状态（``<userData>/diagnostics/compat.json``），不跨设备同步。
 *
 * 本模块不依赖 Electron；main.ts 在 ``app.whenReady()`` 之前读取并应用 flags。
 */
import { mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';

export const CURRENT_SCHEMA = 1;
export const LEVEL_MIN = 0;
export const LEVEL_MAX = 3;

export type CompatLevel = 0 | 1 | 2 | 3;

export interface CompatProfile {
  schema: 1;
  level: CompatLevel;
  flags: string[];
  app: {
    petWindow: boolean;
    previewHost: boolean;
    browserBridge: boolean;
    updateCheck: boolean;
  };
  reason: string;
  updatedAt: string;
  stableBoots?: number;
}

export const LEVEL_FLAGS: Record<number, string[]> = {
  0: [],
  1: ['disable-gpu-compositing', 'disable-accelerated-2d-canvas'],
  2: ['disable-gpu-compositing', 'disable-accelerated-2d-canvas', 'disable-site-isolation-trials'],
  3: [
    'disable-gpu-compositing',
    'disable-accelerated-2d-canvas',
    'disable-site-isolation-trials',
    'single-process',
  ],
};

export const LEVEL_APP_FEATURES: Record<number, CompatProfile['app']> = {
  0: { petWindow: true, previewHost: true, browserBridge: true, updateCheck: true },
  1: { petWindow: false, previewHost: false, browserBridge: true, updateCheck: true },
  2: { petWindow: false, previewHost: false, browserBridge: false, updateCheck: true },
  3: { petWindow: false, previewHost: false, browserBridge: false, updateCheck: false },
};

function assertLevel(level: number): CompatLevel {
  if (!Number.isInteger(level) || level < LEVEL_MIN || level > LEVEL_MAX) {
    throw new Error(`level must be ${LEVEL_MIN}-${LEVEL_MAX}, got ${level}`);
  }
  return level as CompatLevel;
}

export function newProfile(
  level: number = 0,
  reason = '',
  nowIso = new Date().toISOString(),
): CompatProfile {
  const safe = assertLevel(level);
  return {
    schema: CURRENT_SCHEMA,
    level: safe,
    flags: [...LEVEL_FLAGS[safe]],
    app: { ...LEVEL_APP_FEATURES[safe] },
    reason,
    updatedAt: nowIso,
  };
}

export function bumpLevel(profile: CompatProfile, reason: string, nowIso: string): CompatProfile {
  const next = Math.min(LEVEL_MAX, (profile.level ?? 0) + 1);
  const p = newProfile(next, reason, nowIso);
  if (typeof profile.stableBoots === 'number') p.stableBoots = profile.stableBoots;
  return p;
}

export function effectiveFlags(profile: CompatProfile): string[] {
  return [...(LEVEL_FLAGS[profile.level] ?? [])];
}

export function effectiveAppFeatures(profile: CompatProfile): CompatProfile['app'] {
  return { ...(LEVEL_APP_FEATURES[profile.level] ?? LEVEL_APP_FEATURES[0]) };
}

export function readCompatProfile(file: string): CompatProfile {
  try {
    const raw = readFileSync(file, 'utf-8');
    const parsed = JSON.parse(raw) as Partial<CompatProfile>;
    if (!parsed || parsed.schema !== CURRENT_SCHEMA) return newProfile();
    if (
      typeof parsed.level !== 'number' ||
      !Number.isInteger(parsed.level) ||
      parsed.level < LEVEL_MIN ||
      parsed.level > LEVEL_MAX
    ) {
      return newProfile();
    }
    return {
      schema: CURRENT_SCHEMA,
      level: parsed.level as CompatLevel,
      flags: Array.isArray(parsed.flags) ? parsed.flags : [...LEVEL_FLAGS[parsed.level]],
      app: parsed.app ?? { ...LEVEL_APP_FEATURES[parsed.level] },
      reason: typeof parsed.reason === 'string' ? parsed.reason : '',
      updatedAt: typeof parsed.updatedAt === 'string' ? parsed.updatedAt : new Date().toISOString(),
      stableBoots: typeof parsed.stableBoots === 'number' ? parsed.stableBoots : undefined,
    };
  } catch {
    return newProfile();
  }
}

export function writeCompatProfile(file: string, profile: CompatProfile): void {
  mkdirSync(dirname(file), { recursive: true });
  const tmp = `${file}.tmp`;
  writeFileSync(tmp, JSON.stringify(profile, null, 2), 'utf-8');
  renameSync(tmp, file);
}
