/**
 * 字段级 deep merge + 冲突告警.
 *
 * 策略 (默认 'remote-wins'):
 * - 双方都是 plain object → 字段级递归
 * - 双方都是 array (e.g. endpoints[]) → 按 id 去重, 同 id 走字段比较, 不同 console.warn
 * - 标量 / array leaf → override 完全替换 base
 * - 字段值深度不等 (对象对象比较) → console.warn + remote wins
 */
type ConflictPolicy = 'remote-wins' | 'local-wins';

export interface DeepMergeOptions {
  policy?: ConflictPolicy;
  onConflict?: (path: string, base: unknown, override: unknown) => void;
}

export function deepMerge<T>(base: T, override: T, options: DeepMergeOptions = {}): T {
  const { policy = 'remote-wins', onConflict } = options;
  return _merge(base, override, '', policy, onConflict) as T;
}

function _merge(
  base: unknown,
  override: unknown,
  currentPath: string,
  policy: ConflictPolicy,
  onConflict: DeepMergeOptions['onConflict'],
): unknown {
  if (override === undefined || override === null) {
    return base ?? override;
  }
  if (base === undefined || base === null) {
    return override;
  }

  if (Array.isArray(base) && Array.isArray(override)) {
    return _mergeArrays(base, override, currentPath, policy, onConflict);
  }

  if (isPlainObject(base) && isPlainObject(override)) {
    const keys = new Set([...Object.keys(base), ...Object.keys(override)]);
    const result: Record<string, unknown> = {};
    for (const k of keys) {
      const sub = currentPath ? `${currentPath}.${k}` : k;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      result[k] = _merge((base as any)[k], (override as any)[k], sub, policy, onConflict);
    }
    return result;
  }

  if (!deepEqual(base, override)) {
    if (onConflict) {
      onConflict(currentPath, base, override);
    } else {
      console.warn(
        `[deepMerge] conflict on '${currentPath}': ` +
          `base=${JSON.stringify(base)} override=${JSON.stringify(override)}; ${policy}`,
      );
    }
    return policy === 'remote-wins' ? override : base;
  }
  return base;
}

function _mergeArrays(
  base: unknown[],
  override: unknown[],
  currentPath: string,
  policy: ConflictPolicy,
  onConflict: DeepMergeOptions['onConflict'],
): unknown[] {
  const overrideById = new Map<string, unknown>();
  const overrideNoId: unknown[] = [];
  for (const item of override) {
    const id = isPlainObject(item) ? (item as { id?: unknown }).id : undefined;
    if (typeof id === 'string' || typeof id === 'number') {
      overrideById.set(String(id), item);
    } else {
      overrideNoId.push(item);
    }
  }

  const baseById = new Map<string, unknown>();
  for (const item of base) {
    const id = isPlainObject(item) ? (item as { id?: unknown }).id : undefined;
    if (typeof id === 'string' || typeof id === 'number') {
      baseById.set(String(id), item);
    }
  }

  const result: unknown[] = [];
  const seenIds = new Set<string>();

  for (const [id, bItem] of baseById) {
    seenIds.add(id);
    if (overrideById.has(id)) {
      const oItem = overrideById.get(id);
      result.push(_merge(bItem, oItem, `${currentPath}[${id}]`, policy, onConflict));
    } else {
      result.push(bItem);
    }
  }

  for (const [id, oItem] of overrideById) {
    if (!seenIds.has(id)) {
      result.push(oItem);
    }
  }

  for (const item of overrideNoId) {
    result.push(item);
  }

  return result;
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function deepEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (typeof a !== typeof b) return false;
  if (a === null || b === null) return false;
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) return false;
    for (let i = 0; i < a.length; i++) {
      if (!deepEqual(a[i], b[i])) return false;
    }
    return true;
  }
  if (isPlainObject(a) && isPlainObject(b)) {
    const keysA = Object.keys(a);
    const keysB = Object.keys(b);
    if (keysA.length !== keysB.length) return false;
    for (const k of keysA) {
      if (!deepEqual(a[k], b[k])) return false;
    }
    return true;
  }
  return false;
}
