import '@testing-library/jest-dom/vitest';

/**
 * jsdom 29 + vitest 4 的 window.localStorage 是 Storage 实例占位但方法未实现，
 * 直接调用 setItem/getItem 会抛 TypeError。在所有测试运行前注入一个内存版
 * Storage 桩，让依赖 localStorage 的模块（entities/setting/storage 等）能在
 * jsdom 测试环境下工作。
 */
function installInMemoryStorage(key: 'localStorage' | 'sessionStorage'): void {
  const existing = (window as unknown as Record<string, unknown>)[key] as Storage | undefined;
  // 探测原生实现是否真的可用
  if (existing) {
    try {
      existing.setItem('__probe__', '1');
      existing.removeItem('__probe__');
      return;
    } catch {
      // 落入下方桩注入
    }
  }

  const store: Record<string, string> = {};
  const stub: Storage = {
    get length(): number {
      return Object.keys(store).length;
    },
    key(index: number): string | null {
      return Object.keys(store)[index] ?? null;
    },
    getItem(name: string): string | null {
      return Object.prototype.hasOwnProperty.call(store, name) ? store[name] : null;
    },
    setItem(name: string, value: string): void {
      store[name] = String(value);
    },
    removeItem(name: string): void {
      delete store[name];
    },
    clear(): void {
      for (const k of Object.keys(store)) delete store[k];
    },
  };

  Object.defineProperty(window, key, { configurable: true, value: stub });
}

installInMemoryStorage('localStorage');
installInMemoryStorage('sessionStorage');
