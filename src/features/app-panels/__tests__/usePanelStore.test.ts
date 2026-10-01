import { beforeEach, describe, expect, it, vi } from 'vitest';

import { PANEL_STATE_KEY } from '../usePanelStore';

/**
 * usePanelStore 在模块加载时就读 localStorage 决定初态，因此每个用例必须
 * 重新 import 一份干净实例（vi.resetModules + 动态 import）。
 */
async function loadStore() {
  vi.resetModules();
  return (await import('../usePanelStore')).usePanelStore;
}

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe('usePanelStore — 旧键迁移', () => {
  it('从旧键迁移开合与尺寸，并删除旧键', async () => {
    localStorage.setItem('right-panel-open', '1');
    localStorage.setItem('right-panel-width', '480');
    localStorage.setItem('terminal-panel-open', '1');
    localStorage.setItem('terminal-panel-height', '300');
    localStorage.setItem('sidebar-width', '300');

    const store = await loadStore();
    const { slots } = store.getState();

    expect(slots.right.open).toBe(true);
    expect(slots.right.size).toBe(480);
    expect(slots.bottom.open).toBe(true);
    expect(slots.bottom.size).toBe(300);
    expect(slots['left-list'].size).toBe(300);

    // 迁移后旧键必须消失，否则会出现两个真相源
    for (const key of [
      'right-panel-open',
      'right-panel-width',
      'terminal-panel-open',
      'terminal-panel-height',
      'sidebar-width',
    ]) {
      expect(localStorage.getItem(key)).toBeNull();
    }
    expect(localStorage.getItem(PANEL_STATE_KEY)).toBeTruthy();
  });

  it('越界的旧尺寸夹取到槽位边界后迁移', async () => {
    localStorage.setItem('right-panel-width', '9999');
    const store = await loadStore();
    expect(store.getState().slots.right.size).toBe(600);
  });

  it('无旧键时不产生新键（保持惰性）', async () => {
    const store = await loadStore();
    expect(localStorage.getItem(PANEL_STATE_KEY)).toBeNull();
    // 全新用户落默认值
    expect(store.getState().slots.right.size).toBe(320);
    expect(store.getState().slots.right.open).toBe(false);
  });

  it('新键已存在时不再读旧键', async () => {
    localStorage.setItem(
      PANEL_STATE_KEY,
      JSON.stringify({ v: 1, slots: { right: { open: true, active: 'chat-inspector', size: 400 } } }),
    );
    localStorage.setItem('right-panel-width', '280');

    const store = await loadStore();
    expect(store.getState().slots.right.size).toBe(400);
    // 旧键保留（说明确实没走迁移分支）
    expect(localStorage.getItem('right-panel-width')).toBe('280');
  });

  it('新键 JSON 损坏时回落到旧键迁移，再坏则回落默认', async () => {
    localStorage.setItem(PANEL_STATE_KEY, '{not json');
    localStorage.setItem('right-panel-width', '350');
    const store = await loadStore();
    expect(store.getState().slots.right.size).toBe(350);

    localStorage.clear();
    localStorage.setItem(PANEL_STATE_KEY, '{not json');
    const store2 = await loadStore();
    expect(store2.getState().slots.right.size).toBe(320);
  });

  it('localStorage 不可用时降级到内存态（隐私模式）', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('denied');
    });

    const store = await loadStore();
    // 不抛异常，且仍可正常操作
    expect(() => store.getState().setOpen('right', true)).not.toThrow();
    expect(store.getState().slots.right.open).toBe(true);
  });
});

describe('usePanelStore — 槽位互斥', () => {
  it('激活同槽位的另一个面会接管该槽位', async () => {
    const store = await loadStore();
    store.getState().activate('chat-inspector');
    expect(store.getState().slots.right.active).toBe('chat-inspector');

    store.getState().activate('wiki-inspector');
    const right = store.getState().slots.right;
    expect(right.active).toBe('wiki-inspector');
    expect(right.open).toBe(true);
  });

  it('拒绝未在注册表登记的面', async () => {
    const store = await loadStore();
    expect(store.getState().activate('mystery-panel')).toBe(false);
    expect(store.getState().slots.right.active).toBeNull();
  });

  it('最大化右栏时清除底部栏的最大化态（消除浮层压面板的根因）', async () => {
    const store = await loadStore();
    store.getState().setMaximized('bottom', true);
    expect(store.getState().slots.bottom.maximized).toBe(true);

    store.getState().setMaximized('right', true);
    expect(store.getState().slots.right.maximized).toBe(true);
    expect(store.getState().slots.bottom.maximized).toBe(false);
  });

  it('不可最大化的槽位忽略最大化请求', async () => {
    const store = await loadStore();
    store.getState().setMaximized('left-rail', true);
    expect(store.getState().slots['left-rail'].maximized).toBe(false);
  });

  it('关闭槽位会顺带退出最大化', async () => {
    const store = await loadStore();
    store.getState().setMaximized('right', true);
    store.getState().setOpen('right', false);
    expect(store.getState().slots.right.maximized).toBe(false);
    expect(store.getState().slots.right.open).toBe(false);
  });

  it('toggle 与 setSize 走统一口径', async () => {
    const store = await loadStore();
    store.getState().toggle('right');
    expect(store.getState().slots.right.open).toBe(true);
    store.getState().toggle('right');
    expect(store.getState().slots.right.open).toBe(false);

    store.getState().setSize('right', 10);
    expect(store.getState().slots.right.size).toBe(280);
    store.getState().setSize('right', 450);
    expect(store.getState().slots.right.size).toBe(450);
  });

  it('状态变更后持久化内容与内存一致', async () => {
    const store = await loadStore();
    store.getState().activate('chat-inspector');
    store.getState().setSize('right', 500);

    const parsed = JSON.parse(localStorage.getItem(PANEL_STATE_KEY)!);
    expect(parsed.slots.right.active).toBe('chat-inspector');
    expect(parsed.slots.right.open).toBe(true);
    expect(parsed.slots.right.size).toBe(500);
  });
});
