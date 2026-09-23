/**
 * r109: 主题预设数据完整性测试——结构、颜色格式、明暗差异与 id 唯一性。
 *
 * ThemeColors 共 22 个颜色字段；本文件锁定字段全集与取值格式，
 * 防止新增主题时漏字段、写错格式或 base/装饰 id 撞车。
 */
import { describe, expect, it } from 'vitest';

import { decorativePresets } from '../decorative-presets';
import {
  DEFAULT_THEME_ID,
  getThemeById,
  themePresets,
  type ThemeColors,
} from '../presets';

const THEME_COLORS_FIELDS = [
  'primary', 'primaryHover', 'secondary', 'accent',
  'bg', 'bgMuted', 'bgSubtle', 'bgHover', 'bgActive',
  'surface', 'surfaceElevated',
  'text', 'textSecondary', 'textMuted', 'textInverse',
  'border', 'borderHover',
  'success', 'error', 'warning', 'info', 'overlay',
] as const;

const HEX_RE = /^#[0-9a-fA-F]{6}$/;
const RGBA_RE = /^rgba\(\d{1,3},\s?\d{1,3},\s?\d{1,3},\s?(0|1|0?\.\d+)\)$/;

function expectValidThemeColors(colors: ThemeColors, label: string) {
  for (const field of THEME_COLORS_FIELDS) {
    const value = colors[field];
    expect(value, `${label}.${field}`).toBeTruthy();
    expect(
      HEX_RE.test(value) || RGBA_RE.test(value),
      `${label}.${field} 非法颜色值: ${value}`,
    ).toBe(true);
  }
}

function expectReadable(colors: ThemeColors, label: string) {
  expect(colors.text.toLowerCase(), `${label}.text 不应等于 bg`).not.toBe(colors.bg.toLowerCase());
}

describe('themePresets（基础主题）', () => {
  it('包含 6 个基础主题且 id 唯一、顺序稳定', () => {
    expect(themePresets.map((t) => t.id)).toEqual([
      'indigo', 'sage-green', 'ocean', 'ember', 'mono', 'cyberpunk',
    ]);
  });

  it('每个主题明暗两套配色字段齐全且格式合法', () => {
    for (const preset of themePresets) {
      expect(preset.name.trim()).toBeTruthy();
      expect(preset.description.trim()).toBeTruthy();
      expectValidThemeColors(preset.colors, `${preset.id}.colors`);
      expectValidThemeColors(preset.darkColors, `${preset.id}.darkColors`);
    }
  });

  it('明暗主题 bg 不同且暗色 bg 为深色（非纯白）', () => {
    for (const preset of themePresets) {
      expect(preset.colors.bg.toLowerCase()).not.toBe(preset.darkColors.bg.toLowerCase());
      expect(preset.darkColors.bg.toLowerCase()).not.toBe('#ffffff');
    }
  });

  it('明暗两套文案色均与各自背景可读（text ≠ bg）', () => {
    for (const preset of themePresets) {
      expectReadable(preset.colors, `${preset.id}.colors`);
      expectReadable(preset.darkColors, `${preset.id}.darkColors`);
    }
  });
});

describe('decorativePresets（装饰主题）', () => {
  it('5 套装饰主题 id 唯一且带封面/渐变降级', () => {
    expect(decorativePresets.map((t) => t.id)).toEqual([
      'mint-blue', 'sakura', 'cyber-neon', 'midnight-amber', 'parchment',
    ]);
    for (const t of decorativePresets) {
      expect(t.cover.trim()).toBeTruthy();
      expect(t.gradientFrom.trim()).toBeTruthy();
      expect(t.gradientTo.trim()).toBeTruthy();
      expectValidThemeColors(t.colors, `${t.id}.colors`);
      expectValidThemeColors(t.darkColors, `${t.id}.darkColors`);
    }
  });

  it('装饰主题 id 不与基础主题撞车（getThemeById 语义歧义防线）', () => {
    const baseIds = new Set(themePresets.map((t) => t.id));
    for (const t of decorativePresets) {
      expect(baseIds.has(t.id), `装饰主题 id '${t.id}' 与基础主题冲突`).toBe(false);
    }
  });
});

describe('getThemeById / DEFAULT_THEME_ID', () => {
  it('默认主题是基础主题之一', () => {
    expect(themePresets.some((t) => t.id === DEFAULT_THEME_ID)).toBe(true);
    expect(DEFAULT_THEME_ID).toBe('indigo');
  });

  it('基础与装饰主题均可查到，未知 id 返回 undefined', () => {
    expect(getThemeById('indigo')?.id).toBe('indigo');
    expect(getThemeById('mint-blue')?.id).toBe('mint-blue');
    expect(getThemeById('no-such-theme')).toBeUndefined();
  });
});
