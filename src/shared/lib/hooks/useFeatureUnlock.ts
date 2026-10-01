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

/**
 * P1-7: 用户**显式关闭**的 feature 集合（独立于 unlock 集合）。
 *
 * 区分两种"入口不可见"的原因，二者对用户含义完全不同：
 * - 从未使用（既不在 unlock 也不在 disable）→ 不知道功能存在 → 侧栏灰态可见 + 用途引导；
 * - 用户在设置里点了 OFF（在 disable 里）  → 明确表示"不要"      → 侧栏完全隐藏。
 *
 * 混为一谈会侵犯用户显式意图：他把 Arena 开关关掉，却仍看到灰态入口反复提示。
 */
export const FEATURE_DISABLE_STORAGE_KEY = 'sage-feature-disable';

/** 同标签页内跨组件同步用的自定义事件名。 */
export const FEATURE_UNLOCK_EVENT = 'sage:feature-unlock';

/** 同标签页内跨组件同步用的"加锁"自定义事件名。 */
export const FEATURE_UNLOCK_LOCK_EVENT = 'sage:feature-unlock:lock';

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

/** 读取「用户显式关闭」集合，解析失败时安全回退为空集合。 */
function readDisabled(): Set<string> {
  let raw: string | null = null;
  try {
    raw = localStorage.getItem(FEATURE_DISABLE_STORAGE_KEY);
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

/** 将「显式关闭」集合写回 localStorage，写入失败时静默忽略。 */
function writeDisabled(disabled: Set<string>): void {
  try {
    localStorage.setItem(FEATURE_DISABLE_STORAGE_KEY, JSON.stringify([...disabled]));
  } catch {
    /* localStorage unavailable / quota exceeded */
  }
}

/** 该 feature 是否被用户显式关闭（区别于"从未使用"）。 */
export function isFeatureExplicitlyDisabled(featureKey: string): boolean {
  return readDisabled().has(featureKey);
}

/**
 * 永久解锁一个 feature（幂等）。写入 localStorage 并广播自定义事件，
 * 使同标签页内所有 `useFeatureUnlock` 实例同步更新。
 */
export function unlockFeature(featureKey: string): void {
  const unlocked = readUnlocked();
  // 显式解锁（含侧栏引导确认 / 用户重新打开设置开关）时清除"显式关闭"标记，
  // 否则该 feature 会永久停在"用户不要"的隐藏态。
  const disabled = readDisabled();
  const hadDisabled = disabled.delete(featureKey);
  if (hadDisabled) writeDisabled(disabled);
  if (unlocked.has(featureKey) && !hadDisabled) return;
  unlocked.add(featureKey);
  writeUnlocked(unlocked);
  try {
    window.dispatchEvent(new CustomEvent<string>(FEATURE_UNLOCK_EVENT, { detail: featureKey }));
  } catch {
    // 极端环境（无 window / 不支持 CustomEvent）下退化为仅持久化
  }
}

/**
 * 主动加锁一个 feature（幂等）。与 `unlockFeature` 对称，用于"已显式启用但想关闭"的场景
 * ——例如用户在设置中关闭 Arena 自动化开关，希望侧边栏立刻收回。
 *
 * P1-7: 同时记录「用户显式关闭」。该标记让侧栏能把"用户不要"与
 * "用户没试过"区分开：前者完全隐藏，后者灰态可见 + 用途引导。
 */
export function lockFeature(featureKey: string): void {
  const disabled = readDisabled();
  const newlyDisabled = !disabled.has(featureKey);
  if (newlyDisabled) {
    disabled.add(featureKey);
    writeDisabled(disabled);
  }
  const unlocked = readUnlocked();
  if (!unlocked.has(featureKey)) {
    // 原本就未解锁：无 UI 状态变化可广播，但新写入的"显式关闭"仍需通知订阅者
    if (newlyDisabled) dispatchLockEvent(featureKey);
    return;
  }
  unlocked.delete(featureKey);
  writeUnlocked(unlocked);
  dispatchLockEvent(featureKey);
}

function dispatchLockEvent(featureKey: string): void {
  try {
    window.dispatchEvent(
      new CustomEvent<string>(FEATURE_UNLOCK_LOCK_EVENT, { detail: featureKey }),
    );
  } catch {
    // 极端环境下退化为仅持久化
  }
}

/**
 * P1-7: 订阅「用户显式关闭」状态。
 *
 * 与 `useFeatureUnlock` 分开而非扩展其返回值 —— 后者的二元组已被
 * Sidebar / ArenaAccountsToggle 等多处消费，改形状会波及无关调用方。
 *
 * 用途：侧栏据此区分「用户不要」（完全隐藏）与「用户没试过」（灰态 + 引导）。
 */
export function useFeatureExplicitlyDisabled(featureKey: string): boolean {
  const [disabled, setDisabled] = useState<boolean>(() => isFeatureExplicitlyDisabled(featureKey));

  useEffect(() => {
    const sync = () => setDisabled(isFeatureExplicitlyDisabled(featureKey));
    sync();
    const onUnlockOrLock = (event: Event) => {
      if ((event as CustomEvent<string>).detail === featureKey) sync();
    };
    const onStorage = (event: StorageEvent) => {
      if (
        event.key === FEATURE_DISABLE_STORAGE_KEY ||
        event.key === FEATURE_UNLOCK_STORAGE_KEY ||
        event.key === null
      ) {
        sync();
      }
    };
    window.addEventListener(FEATURE_UNLOCK_EVENT, onUnlockOrLock);
    window.addEventListener(FEATURE_UNLOCK_LOCK_EVENT, onUnlockOrLock);
    window.addEventListener('storage', onStorage);
    return () => {
      window.removeEventListener(FEATURE_UNLOCK_EVENT, onUnlockOrLock);
      window.removeEventListener(FEATURE_UNLOCK_LOCK_EVENT, onUnlockOrLock);
      window.removeEventListener('storage', onStorage);
    };
  }, [featureKey]);

  return disabled;
}

/**
 * 订阅某 feature 的解锁状态。
 *
 * @returns `[isUnlocked, setUnlocked]`
 *   - `isUnlocked`：该 feature 是否已解锁（初始值从 localStorage hydrate）。
 *   - `setUnlocked(true)`：永久解锁；`setUnlocked(false)`：永久加锁。
 *
 * 同步机制：
 *   - 同标签页：监听 `FEATURE_UNLOCK_EVENT` / `FEATURE_UNLOCK_LOCK_EVENT` 自定义事件。
 *   - 跨标签页：监听 `storage` 事件。
 */
export function useFeatureUnlock(featureKey: string): [boolean, (next: boolean) => void] {
  const [unlocked, setUnlockedState] = useState<boolean>(() => isFeatureUnlocked(featureKey));

  useEffect(() => {
    // 挂载 / featureKey 变化时重新同步，堵住 render→subscribe 之间的理论竞态窗口，
    // 并保证动态 key 场景下不会停留在旧 key 的状态。
    setUnlockedState(isFeatureUnlocked(featureKey));
    const onUnlock = (event: Event) => {
      const detail = (event as CustomEvent<string>).detail;
      if (detail === featureKey) {
        setUnlockedState(true);
      }
    };
    const onLock = (event: Event) => {
      const detail = (event as CustomEvent<string>).detail;
      if (detail === featureKey) {
        setUnlockedState(false);
      }
    };
    const onStorage = (event: StorageEvent) => {
      if (event.key === FEATURE_UNLOCK_STORAGE_KEY || event.key === null) {
        setUnlockedState(isFeatureUnlocked(featureKey));
      }
    };
    window.addEventListener(FEATURE_UNLOCK_EVENT, onUnlock);
    window.addEventListener(FEATURE_UNLOCK_LOCK_EVENT, onLock);
    window.addEventListener('storage', onStorage);
    return () => {
      window.removeEventListener(FEATURE_UNLOCK_EVENT, onUnlock);
      window.removeEventListener(FEATURE_UNLOCK_LOCK_EVENT, onLock);
      window.removeEventListener('storage', onStorage);
    };
  }, [featureKey]);

  const setUnlocked = useCallback(
    (next: boolean): void => {
      if (next) {
        unlockFeature(featureKey);
      } else {
        lockFeature(featureKey);
      }
    },
    [featureKey],
  );

  return [unlocked, setUnlocked];
}
