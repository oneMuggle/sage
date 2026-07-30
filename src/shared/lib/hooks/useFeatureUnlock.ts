import { useCallback, useEffect, useState } from 'react';

/**
 * Sticky-Unlock Chips / 渐进式功能披露 (U10)
 *
 * 高级功能入口（如 Skills / Orchestration / Office）在首次使用前从 sidebar 隐藏，
 * 首次使用后永久解锁（写入 localStorage），之后始终显示。
 *
 * 参考 OpenWorker `Sidebar.tsx` 的 inbox chip "sticky unlock" 模式：
 * 默认不可见，一旦产品首次需要它即永久出现（per-device）。
 *
 * 存储形态：`sage-feature-unlock` → 已解锁 feature key 的 JSON 字符串数组。
 * 用数组而非 Set，因为 Set 无法被 `JSON.stringify` 序列化为有意义的内容。
 */

/** localStorage 存储键（所有 feature 共享一个 store）。 */
export const FEATURE_UNLOCK_STORAGE_KEY = 'sage-feature-unlock';

/** 同标签页内跨组件同步用的自定义事件名。 */
export const FEATURE_UNLOCK_EVENT = 'sage:feature-unlock';

/** 从 localStorage 读取已解锁集合，解析失败时安全回退为空集合。 */
function readUnlocked(): Set<string> {
  let raw: string | null = null;
  try {
    raw = localStorage.getItem(FEATURE_UNLOCK_STORAGE_KEY);
  } catch {
    return new Set();
  }
  if (!raw) return new Set();
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((x): x is string => typeof x === 'string'));
  } catch {
    return new Set();
  }
}

/** 将已解锁集合写回 localStorage，写入失败（配额/不可用）时静默忽略。 */
function writeUnlocked(unlocked: Set<string>): void {
  try {
    localStorage.setItem(FEATURE_UNLOCK_STORAGE_KEY, JSON.stringify([...unlocked]));
  } catch {
    // localStorage unavailable / quota exceeded — 解锁状态仅在内存中生效
  }
}

/** 某 feature 是否已解锁（命令式读取，供 effect / 非组件代码使用）。 */
export function isFeatureUnlocked(featureKey: string): boolean {
  return readUnlocked().has(featureKey);
}

/**
 * 永久解锁一个 feature（幂等）。写入 localStorage 并广播自定义事件，
 * 使同标签页内所有 `useFeatureUnlock` 实例同步更新。
 */
export function unlockFeature(featureKey: string): void {
  const unlocked = readUnlocked();
  if (unlocked.has(featureKey)) return;
  unlocked.add(featureKey);
  writeUnlocked(unlocked);
  try {
    window.dispatchEvent(new CustomEvent<string>(FEATURE_UNLOCK_EVENT, { detail: featureKey }));
  } catch {
    // 极端环境（无 window / 不支持 CustomEvent）下退化为仅持久化
  }
}

/**
 * 订阅某 feature 的解锁状态。
 *
 * @returns `[isUnlocked, unlock]`
 *   - `isUnlocked`：该 feature 是否已解锁（初始值从 localStorage hydrate）。
 *   - `unlock`：永久解锁该 feature。
 *
 * 同步机制：
 *   - 同标签页：监听 `FEATURE_UNLOCK_EVENT` 自定义事件（`unlockFeature` 触发）。
 *   - 跨标签页：监听 `storage` 事件。
 */
export function useFeatureUnlock(featureKey: string): [boolean, () => void] {
  const [unlocked, setUnlocked] = useState<boolean>(() => isFeatureUnlocked(featureKey));

  useEffect(() => {
    // 挂载 / featureKey 变化时重新同步，堵住 render→subscribe 之间的理论竞态窗口，
    // 并保证动态 key 场景下不会停留在旧 key 的状态。
    setUnlocked(isFeatureUnlocked(featureKey));
    const onUnlock = (event: Event) => {
      const detail = (event as CustomEvent<string>).detail;
      if (detail === featureKey) {
        setUnlocked(true);
      }
    };
    const onStorage = (event: StorageEvent) => {
      if (event.key === FEATURE_UNLOCK_STORAGE_KEY || event.key === null) {
        setUnlocked(isFeatureUnlocked(featureKey));
      }
    };
    window.addEventListener(FEATURE_UNLOCK_EVENT, onUnlock);
    window.addEventListener('storage', onStorage);
    return () => {
      window.removeEventListener(FEATURE_UNLOCK_EVENT, onUnlock);
      window.removeEventListener('storage', onStorage);
    };
  }, [featureKey]);

  const unlock = useCallback(() => unlockFeature(featureKey), [featureKey]);

  return [unlocked, unlock];
}
