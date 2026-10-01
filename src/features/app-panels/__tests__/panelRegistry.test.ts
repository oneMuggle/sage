import { describe, expect, it } from 'vitest';

import {
  clampSize,
  getPanelDefinition,
  isExclusiveConflict,
  isRegisteredPanel,
  panelsForSlot,
  PANEL_DEFINITIONS,
  PANEL_SLOT_IDS,
  PANEL_SLOTS,
  slotGeometry,
  type PanelMigrationBatch,
} from '../panelRegistry';

describe('panelRegistry', () => {
  it('登记了本次审计发现的全部侧边面', () => {
    // 四套并存的右/底/浮层实现必须都能在注册表里查到，否则迁移时会漏
    expect(isRegisteredPanel('chat-inspector')).toBe(true);
    expect(isRegisteredPanel('wiki-inspector')).toBe(true);
    expect(isRegisteredPanel('model-catalog-detail')).toBe(true);
    expect(isRegisteredPanel('terminal')).toBe(true);
    expect(isRegisteredPanel('task-center')).toBe(true);
  });

  it('每个面板都声明了所属槽位与迁移批次', () => {
    const validBatches: readonly PanelMigrationBatch[] = ['A', 'B', 'C', 'D'];
    for (const def of PANEL_DEFINITIONS) {
      expect(PANEL_SLOTS[def.slot]).toBeDefined();
      expect(validBatches).toContain(def.migrationBatch);
      // 未接入统一槽位前必须写明现状落点，否则迁移时无从核对
      expect(def.currentOwner).toBeTruthy();
    }
  });

  it('面板 id 不重复', () => {
    const ids = PANEL_DEFINITIONS.map((p) => p.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('左栏三项内容列表共用 left-list 槽位（互斥的基础）', () => {
    const ids = panelsForSlot('left-list').map((p) => p.id);
    expect(ids).toEqual(['sider-projects', 'sider-conversations', 'sider-git']);
    expect(slotGeometry('left-list').exclusive).toBe(true);
  });

  it('right 槽位容纳三套右栏实现且互斥', () => {
    const ids = panelsForSlot('right').map((p) => p.id);
    expect(ids).toEqual(['chat-inspector', 'wiki-inspector', 'model-catalog-detail']);
    expect(slotGeometry('right').exclusive).toBe(true);
  });

  it('floating 槽位不互斥（允许与其它面并存）', () => {
    expect(slotGeometry('floating').exclusive).toBe(false);
    expect(getPanelDefinition('task-center')?.slot).toBe('floating');
  });

  it('同槽位互斥、跨槽位不互斥', () => {
    expect(isExclusiveConflict('chat-inspector', 'wiki-inspector')).toBe(true);
    expect(isExclusiveConflict('sider-projects', 'sider-git')).toBe(true);
    expect(isExclusiveConflict('chat-inspector', 'terminal')).toBe(false);
    expect(isExclusiveConflict('task-center', 'chat-inspector')).toBe(false);
  });

  it('未登记的 id 不产生互斥判定', () => {
    expect(isRegisteredPanel('not-a-panel')).toBe(false);
    expect(getPanelDefinition('not-a-panel')).toBeUndefined();
    expect(isExclusiveConflict('not-a-panel', 'chat-inspector')).toBe(false);
  });

  it('每个槽位都有几何定义，尺寸边界自洽', () => {
    for (const slot of PANEL_SLOT_IDS) {
      const g = slotGeometry(slot);
      expect(g.minSize).toBeLessThanOrEqual(g.defaultSize);
      expect(g.defaultSize).toBeLessThanOrEqual(g.maxSize);
    }
  });

  it('尺寸夹取：越界夹到边界、脏值回落默认', () => {
    // 右栏边界沿用现状 useResizablePanel 的 280~600
    expect(clampSize('right', 100)).toBe(280);
    expect(clampSize('right', 9999)).toBe(600);
    expect(clampSize('right', 440)).toBe(440);
    expect(clampSize('right', Number.NaN)).toBe(320);
    expect(clampSize('right', Number.POSITIVE_INFINITY)).toBe(320);
    // 底部轴向是高度
    expect(clampSize('bottom', 50)).toBe(120);
    expect(clampSize('bottom', 1000)).toBe(600);
  });
});
