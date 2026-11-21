import { beforeEach, describe, expect, it } from 'vitest';

import { deletePreset, loadPresets, savePreset } from '../designTweakPresets';

describe('designTweakPresets', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('saves, lists and overwrites presets by name', () => {
    savePreset('warm', { accent: '#cc2200', radius: 12, font_size: null });
    savePreset('cool', { accent: '#003366' });
    savePreset('warm', { accent: '#881100', radius: 4 });

    const presets = loadPresets();
    expect(presets.map((preset) => preset.name)).toEqual(['warm', 'cool']);
    expect(presets[0].tweaks.accent).toBe('#881100');
    expect(presets[0].tweaks.radius).toBe(4);
  });

  it('omits null fields when saving', () => {
    savePreset('compact', { accent: null, radius: 6, density: null });
    const [preset] = loadPresets();
    expect(preset.tweaks).toEqual({ radius: 6 });
  });

  it('ignores empty names and deletes by name', () => {
    savePreset('  ', { accent: '#000000' });
    expect(loadPresets()).toHaveLength(0);

    savePreset('one', { accent: '#111111' });
    savePreset('two', { accent: '#222222' });
    const remaining = deletePreset('one');
    expect(remaining.map((preset) => preset.name)).toEqual(['two']);
    expect(loadPresets().map((preset) => preset.name)).toEqual(['two']);
  });

  it('returns an empty list for corrupt storage', () => {
    window.localStorage.setItem('sage.design.tweakPresets', '{not json');
    expect(loadPresets()).toEqual([]);
  });
});
