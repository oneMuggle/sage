// 任务栏注意力提示测试 (2026-11-05)
import { describe, expect, it, vi } from 'vitest';

import { applyTaskbarAttention, decideTaskbarAttention } from '../notifyOverlay';

describe('decideTaskbarAttention', () => {
  it('优先级：等待审批 > 失败 > 完成', () => {
    expect(decideTaskbarAttention({ awaitingApproval: 2, failed: 3, completed: 4 })).toEqual({
      count: 2,
      kind: 'awaiting_approval',
    });
    expect(decideTaskbarAttention({ failed: 3, completed: 4 })).toEqual({
      count: 3,
      kind: 'failed',
    });
    expect(decideTaskbarAttention({ completed: 4 })).toEqual({
      count: 4,
      kind: 'completed',
    });
    expect(decideTaskbarAttention({})).toEqual({ count: 0, kind: null });
  });

  it('负值按 0 处理，且不产生注意力', () => {
    expect(decideTaskbarAttention({ awaitingApproval: -3 })).toEqual({ count: 0, kind: null });
  });
});

function fakeWindow(focused: boolean) {
  return {
    isDestroyed: () => false,
    isFocused: () => focused,
    flashFrame: vi.fn(),
  };
}

describe('applyTaskbarAttention', () => {
  it('窗口失焦且有注意力 → flashFrame(true)', () => {
    const win = fakeWindow(false);
    applyTaskbarAttention(
      { count: 2, kind: 'awaiting_approval' },
      { win: win as never, platform: 'win32' },
    );
    expect(win.flashFrame).toHaveBeenCalledWith(true);
  });

  it('窗口在前台 → 不闪烁', () => {
    const win = fakeWindow(true);
    applyTaskbarAttention(
      { count: 2, kind: 'awaiting_approval' },
      { win: win as never, platform: 'win32' },
    );
    expect(win.flashFrame).not.toHaveBeenCalled();
  });

  it('count=0 → 停止闪烁并清空 dock badge', () => {
    const win = fakeWindow(false);
    const setDockBadge = vi.fn();
    applyTaskbarAttention(
      { count: 0, kind: null },
      { win: win as never, platform: 'darwin', setDockBadge },
    );
    expect(win.flashFrame).toHaveBeenCalledWith(false);
    expect(setDockBadge).toHaveBeenCalledWith('');
  });

  it('macOS 写入 dock badge 数字', () => {
    const win = fakeWindow(true);
    const setDockBadge = vi.fn();
    applyTaskbarAttention(
      { count: 3, kind: 'failed' },
      { win: win as never, platform: 'darwin', setDockBadge },
    );
    expect(setDockBadge).toHaveBeenCalledWith('3');
  });

  it('窗口为空或已销毁时安全返回', () => {
    expect(() =>
      applyTaskbarAttention({ count: 1, kind: 'failed' }, { win: null, platform: 'win32' }),
    ).not.toThrow();
    const destroyed = {
      isDestroyed: () => true,
      isFocused: () => false,
      flashFrame: vi.fn(),
    };
    applyTaskbarAttention(
      { count: 1, kind: 'failed' },
      { win: destroyed as never, platform: 'win32' },
    );
    expect(destroyed.flashFrame).not.toHaveBeenCalled();
  });
});
