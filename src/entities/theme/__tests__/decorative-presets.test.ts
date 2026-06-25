import { describe, expect, it } from 'vitest';

import { decorativePresets, findDecorativeThemeById } from '../decorative-presets';

describe('decorative-presets', () => {
  it('导出 5 套装饰主题', () => {
    expect(decorativePresets).toHaveLength(5);
  });

  it('每套主题都有必需字段', () => {
    for (const theme of decorativePresets) {
      expect(theme.id).toBeTruthy();
      expect(theme.name).toBeTruthy();
      expect(theme.description).toBeTruthy();
      expect(theme.cover).toMatch(/\.svg$/);
      expect(theme.gradientFrom).toMatch(/^#/);
      expect(theme.gradientTo).toMatch(/^#/);
      expect(theme.colors).toBeDefined();
      expect(theme.darkColors).toBeDefined();
    }
  });

  it('ID 唯一', () => {
    const ids = decorativePresets.map((t) => t.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('包含 5 个指定 ID', () => {
    const ids = decorativePresets.map((t) => t.id);
    expect(ids).toContain('mint-blue');
    expect(ids).toContain('sakura');
    expect(ids).toContain('cyber-neon');
    expect(ids).toContain('midnight-amber');
    expect(ids).toContain('parchment');
  });

  it('findDecorativeThemeById 命中时返回主题', () => {
    const theme = findDecorativeThemeById('sakura');
    expect(theme).toBeDefined();
    expect(theme?.id).toBe('sakura');
  });

  it('findDecorativeThemeById 未命中时返回 undefined', () => {
    expect(findDecorativeThemeById('nonexistent')).toBeUndefined();
  });

  it('颜色对象包含所有 ThemeColors 字段', () => {
    const requiredKeys = [
      'primary',
      'primaryHover',
      'secondary',
      'accent',
      'bg',
      'bgMuted',
      'bgSubtle',
      'bgHover',
      'bgActive',
      'surface',
      'surfaceElevated',
      'text',
      'textSecondary',
      'textMuted',
      'textInverse',
      'border',
      'borderHover',
      'success',
      'error',
      'warning',
      'info',
      'overlay',
    ];
    for (const theme of decorativePresets) {
      for (const key of requiredKeys) {
        expect(theme.colors).toHaveProperty(key);
        expect(theme.darkColors).toHaveProperty(key);
      }
    }
  });
});
