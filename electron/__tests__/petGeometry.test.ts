import { describe, expect, it } from 'vitest';

import {
  clampToWorkArea,
  defaultPosition,
  isPointInRect,
  petHitBox,
  petWindowSize,
} from '../pet/geometry';

describe('pet geometry', () => {
  it('keeps a 16:9 pet body plus bubble strip', () => {
    expect(petWindowSize('medium')).toEqual({ width: 300, height: 241 });
    expect(petWindowSize('mini')).toEqual({ width: 160, height: 162 });
  });

  it('clamps windows into the work area', () => {
    const workArea = { x: 0, y: 0, width: 1280, height: 720 };
    const size = { width: 300, height: 241 };
    expect(clampToWorkArea({ x: -50, y: 900 }, size, workArea)).toEqual({ x: 0, y: 479 });
    expect(clampToWorkArea({ x: 500, y: 200 }, size, workArea)).toEqual({ x: 500, y: 200 });
  });

  it('places the pet in the bottom-right corner by default', () => {
    const workArea = { x: 0, y: 0, width: 1280, height: 720 };
    expect(defaultPosition(workArea, { width: 300, height: 241 }, 24)).toEqual({
      x: 956,
      y: 455,
    });
  });

  it('uses the central body as the interaction hit box', () => {
    const bounds = { x: 100, y: 100, width: 300, height: 241 };
    const hit = petHitBox(bounds);
    expect(isPointInRect({ x: 250, y: 300 }, hit)).toBe(true);
    expect(isPointInRect({ x: 110, y: 300 }, hit)).toBe(false);
    expect(isPointInRect({ x: 250, y: 110 }, hit)).toBe(false);
  });
});
