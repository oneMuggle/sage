// src/features/send-message/__tests__/sessionNotify.test.ts
// S8 分会话通知: 打扰判定纯逻辑 + 无桥降级 no-op。
import { describe, it, expect, vi } from 'vitest';

import { notifySession, shouldNotify } from '../sessionNotify';

describe('shouldNotify', () => {
  it('非当前查看的会话 → 通知', () => {
    expect(shouldNotify('sess-a', 'sess-b')).toBe(true);
  });

  it('当前查看的会话且窗口可见 → 不打扰', () => {
    expect(shouldNotify('sess-a', 'sess-a')).toBe(false);
  });

  it('窗口不可见时即使当前会话也通知', () => {
    const original = document.visibilityState;
    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      get: () => 'hidden',
    });
    try {
      expect(shouldNotify('sess-a', 'sess-a')).toBe(true);
    } finally {
      Object.defineProperty(document, 'visibilityState', {
        configurable: true,
        get: () => original,
      });
    }
  });

  it('/btw 伪会话永不通知', () => {
    expect(shouldNotify('__btw__', 'sess-a')).toBe(false);
    expect(shouldNotify('__btw__', null)).toBe(false);
  });
});

describe('notifySession', () => {
  it('无 electron 桥时静默 no-op 不抛错', () => {
    const original = window.electronAPI;
    // jsdom 下 electronAPI 缺失（或显式清空）
    Object.defineProperty(window, 'electronAPI', {
      configurable: true,
      get: () => undefined,
    });
    try {
      expect(() =>
        notifySession({ sessionId: 's1', title: 't', body: 'b' }),
      ).not.toThrow();
    } finally {
      Object.defineProperty(window, 'electronAPI', {
        configurable: true,
        get: () => original,
      });
    }
  });

  it('有桥时透传 payload;桥拒绝也不抛错', async () => {
    const notify = vi.fn().mockResolvedValue({ shown: true });
    const original = window.electronAPI;
    Object.defineProperty(window, 'electronAPI', {
      configurable: true,
      get: () => ({ notifySession: notify }),
    });
    try {
      notifySession({ sessionId: 's1', title: '标题', body: '正文' });
      await Promise.resolve();
      expect(notify).toHaveBeenCalledWith({ sessionId: 's1', title: '标题', body: '正文' });
    } finally {
      Object.defineProperty(window, 'electronAPI', {
        configurable: true,
        get: () => original,
      });
    }
  });
});
