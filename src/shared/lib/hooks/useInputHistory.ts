import { useCallback, useState } from 'react';

const HISTORY_KEY = 'sage-input-history';
const DEFAULT_MAX_SIZE = 50;

interface HistoryStore {
  [sessionId: string]: string[];
}

/**
 * 读取 localStorage 中存储的输入历史大小限制。
 * 返回 DEFAULT_MAX_SIZE 如果未设置或解析失败。
 */
function getMaxHistorySize(): number {
  try {
    const value = localStorage.getItem('sage:input-history-size');
    if (value === null) return DEFAULT_MAX_SIZE;
    const parsed = parseInt(value, 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_MAX_SIZE;
  } catch {
    return DEFAULT_MAX_SIZE;
  }
}

/**
 * 按会话 ID 管理输入历史（最近发送的消息）。
 *
 * 功能：
 * - 每个会话独立存储历史
 * - 保留最近 N 条（N 可通过设置配置，默认 50）
 * - 去重：连续相同内容不重复记录
 * - 最新条目在数组头部（index 0）
 *
 * @param sessionId - 当前会话 ID（null = 不使用历史）
 * @returns { history, addToHistory, clearHistory }
 */
export function useInputHistory(sessionId: string | null): {
  history: string[];
  addToHistory: (content: string) => void;
  clearHistory: () => void;
} {
  const [history, setHistory] = useState<string[]>(() => {
    if (!sessionId) return [];
    try {
      const store = JSON.parse(localStorage.getItem(HISTORY_KEY) ?? '{}') as HistoryStore;
      return store[sessionId] ?? [];
    } catch {
      return [];
    }
  });

  /**
   * 将新内容添加到历史头部。
   * - 空内容被忽略
   * - 与最新条目相同的内容被忽略（去重）
   * - 超出 maxSize 的条目被截断
   */
  const addToHistory = useCallback(
    (content: string) => {
      if (!sessionId) return;
      const trimmed = content.trim();
      if (!trimmed) return;

      const maxSize = getMaxHistorySize();

      setHistory((prev) => {
        // 去重：与最新条目相同则不添加
        if (prev.length > 0 && prev[0] === trimmed) {
          return prev;
        }

        const next = [trimmed, ...prev].slice(0, maxSize);

        // 持久化
        try {
          const store = JSON.parse(localStorage.getItem(HISTORY_KEY) ?? '{}') as HistoryStore;
          store[sessionId] = next;
          localStorage.setItem(HISTORY_KEY, JSON.stringify(store));
        } catch {
          // privacy mode or quota exceeded — silently fail
        }

        return next;
      });
    },
    [sessionId],
  );

  /**
   * 清空当前会话的历史。
   */
  const clearHistory = useCallback(() => {
    if (!sessionId) return;

    setHistory([]);

    try {
      const store = JSON.parse(localStorage.getItem(HISTORY_KEY) ?? '{}') as HistoryStore;
      delete store[sessionId];
      localStorage.setItem(HISTORY_KEY, JSON.stringify(store));
    } catch {
      // privacy mode or quota exceeded — silently fail
    }
  }, [sessionId]);

  return { history, addToHistory, clearHistory };
}

/**
 * 删除会话时清理其历史 — 由 deleteSessionCascade 调用。
 */
export function clearSessionInputHistory(sessionId: string): void {
  try {
    const store = JSON.parse(localStorage.getItem(HISTORY_KEY) ?? '{}') as HistoryStore;
    if (sessionId in store) {
      delete store[sessionId];
      localStorage.setItem(HISTORY_KEY, JSON.stringify(store));
    }
  } catch {
    // privacy mode or quota exceeded — same tolerance as writes
  }
}

/**
 * 设置输入历史的最大条数（持久化到 localStorage）。
 * 由 Settings UI 调用。
 */
export function setInputHistorySize(size: number): void {
  try {
    const validSize = Math.max(1, Math.min(200, Math.trunc(size)));
    localStorage.setItem('sage:input-history-size', String(validSize));
  } catch {
    // privacy mode — silently fail
  }
}

/**
 * 获取当前配置的输入历史大小。
 */
export function getInputHistorySize(): number {
  return getMaxHistorySize();
}

export function auditUseInputHistoryGovernance(): string {
  return JSON.stringify(
    {
      schema: 'sage.shared.lib.hooks.use_input_history.governance.v1',
      phase: 'P182',
      storageKey: HISTORY_KEY,
      configKey: 'sage:input-history-size',
      defaultMaxSize: DEFAULT_MAX_SIZE,
    },
    null,
    2,
  );
}
