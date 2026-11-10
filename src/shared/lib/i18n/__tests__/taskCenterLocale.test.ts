import { describe, expect, it } from 'vitest';

import { en } from '../en';
import { zh } from '../zh';

const PREFIXES = [
  'taskCenter.section.',
  'taskCenter.source.',
  'taskCenter.group.',
  'taskCenter.action.',
  'taskCenter.filter.',
  'taskCenter.page.',
  'taskCenter.badge.',
];

describe('i18n / taskCenter 文案域', () => {
  const zhKeys = Object.keys(zh)
    .filter((k) => PREFIXES.some((p) => k.startsWith(p)))
    .sort();
  const enKeys = Object.keys(en)
    .filter((k) => PREFIXES.some((p) => k.startsWith(p)))
    .sort();

  it('存在新增子树', () => {
    expect(zhKeys.length).toBeGreaterThan(20);
  });

  it('中英文键集完全一致', () => {
    expect(enKeys).toEqual(zhKeys);
  });

  it('所有值非空', () => {
    for (const key of zhKeys) {
      expect((zh as Record<string, string>)[key]?.length ?? 0).toBeGreaterThan(0);
      expect((en as Record<string, string>)[key]?.length ?? 0).toBeGreaterThan(0);
    }
  });

  it('新键不与既有 taskCenter.* 键重名（spread 聚合会静默覆盖）', () => {
    // 既有的扁平键（taskCenter.cancel / clearFinished / status.*）必须仍在，
    // 且新域不得覆盖它们
    expect((zh as Record<string, string>)['taskCenter.cancel']).toBeTruthy();
    expect((zh as Record<string, string>)['taskCenter.action.cancel']).toBeTruthy();
    expect((zh as Record<string, string>)['taskCenter.cancel']).not.toBe(
      (zh as Record<string, string>)['taskCenter.action.cancel'],
    );
  });
});
