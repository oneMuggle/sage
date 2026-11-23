/**
 * orchNotifications — 待展示通知 → OS 通知 + 点击深链（M4.3a）。
 *
 * 覆盖三件事：
 *   1. 标题/正文按上限截断后展示
 *   2. 带 run_id 的编排通知点击时聚焦窗口 + 回发深链锚点
 *   3. 不带 run_id 的通知保持"仅展示"（无点击回发）
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

interface FakeNotification {
  options: Record<string, unknown>;
  handlers: Record<string, Array<() => void>>;
  show: () => void;
  fire: (event: string) => void;
}

const h = vi.hoisted(() => {
  const created: Array<FakeNotification> = [];
  return {
    created,
    isSupported: vi.fn(() => true),
  };
});

vi.mock('electron', () => ({
  Notification: class {
    static isSupported = h.isSupported;
    options: Record<string, unknown>;
    handlers: Record<string, Array<() => void>> = {};
    constructor(options: Record<string, unknown>) {
      this.options = options;
      h.created.push(this as unknown as FakeNotification);
    }
    on(event: string, cb: () => void): this {
      (this.handlers[event] ??= []).push(cb);
      return this;
    }
    show(): void {
      /* 记录即可 */
    }
    fire(event: string): void {
      (this.handlers[event] ?? []).forEach((cb) => cb());
    }
  },
}));

function makeWindow() {
  return {
    isDestroyed: () => false,
    isMinimized: () => true,
    restore: vi.fn(),
    show: vi.fn(),
    focus: vi.fn(),
    webContents: { send: vi.fn() },
  };
}

beforeEach(() => {
  h.created.length = 0;
  h.isSupported.mockReset();
  h.isSupported.mockReturnValue(true);
});

describe('showPendingNotification', () => {
  it('按上限截断标题与正文后展示通知', async () => {
    const { showPendingNotification } = await import('../orchNotifications');
    showPendingNotification({ title: 'x'.repeat(200), body: 'y'.repeat(400) }, () => null);
    expect(h.created).toHaveLength(1);
    expect(h.created[0].options.title).toHaveLength(120);
    expect(h.created[0].options.body).toHaveLength(200);
    expect(h.created[0].options.silent).toBe(false);
  });

  it('系统不支持通知时直接跳过', async () => {
    h.isSupported.mockReturnValue(false);
    const { showPendingNotification } = await import('../orchNotifications');
    showPendingNotification({ title: 'A' }, () => null);
    expect(h.created).toHaveLength(0);
  });

  it('带 run_id 的通知点击时聚焦窗口并回发深链锚点', async () => {
    const { showPendingNotification, ORCH_NOTIFY_CLICK_EVENT } =
      await import('../orchNotifications');
    const win = makeWindow();
    showPendingNotification(
      { title: '✅ 编排运行完成', run_id: 'orch-1', task_id: 'task-7', session_id: 's-42' },
      () => win as never,
    );
    h.created[0].fire('click');
    expect(win.restore).toHaveBeenCalled();
    expect(win.show).toHaveBeenCalled();
    expect(win.focus).toHaveBeenCalled();
    expect(win.webContents.send).toHaveBeenCalledWith(ORCH_NOTIFY_CLICK_EVENT, {
      sessionId: 's-42',
      runId: 'orch-1',
      taskId: 'task-7',
    });
  });

  it('不带 run_id 的通知点击时不回发深链', async () => {
    const { showPendingNotification } = await import('../orchNotifications');
    const win = makeWindow();
    showPendingNotification({ title: '⏰ 待办紧急' }, () => win as never);
    h.created[0].fire('click');
    expect(win.webContents.send).not.toHaveBeenCalled();
  });

  it('窗口已销毁时点击不炸', async () => {
    const { showPendingNotification } = await import('../orchNotifications');
    showPendingNotification(
      { title: 'A', run_id: 'orch-1' },
      () =>
        ({
          isDestroyed: () => true,
          isMinimized: () => false,
          restore: vi.fn(),
          show: vi.fn(),
          focus: vi.fn(),
          webContents: { send: vi.fn() },
        }) as never,
    );
    expect(() => h.created[0].fire('click')).not.toThrow();
  });
});

describe('toClickTarget', () => {
  it('缺字段时补空串', async () => {
    const { toClickTarget } = await import('../orchNotifications');
    expect(toClickTarget({})).toEqual({ sessionId: '', runId: '', taskId: '' });
  });
});
