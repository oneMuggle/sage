/**
 * @vitest-environment jsdom
 */
import { describe, expect, it } from 'vitest';
import {
  defaultRecommendations,
  lucideIconMap,
  type AssistantRecommendation,
} from '../recommendations';

describe('recommendations data', () => {
  it('exports exactly 3 default recommendations', () => {
    expect(defaultRecommendations).toHaveLength(3);
  });

  it('every recommendation has all required fields', () => {
    defaultRecommendations.forEach((rec: AssistantRecommendation) => {
      expect(rec.id).toBeTruthy();
      expect(rec.title).toBeTruthy();
      expect(rec.prompt).toBeTruthy();
      expect(rec.icon).toBeTruthy();
      expect(rec.gradient).toBeTruthy();
    });
  });

  it('every icon name has a corresponding lucide icon component', () => {
    defaultRecommendations.forEach((rec) => {
      expect(lucideIconMap[rec.icon]).toBeDefined();
    });
  });

  it('default recommendations include code, search, and idea themes', () => {
    const ids = defaultRecommendations.map((r) => r.id);
    expect(ids).toContain('code');
    expect(ids).toContain('search');
    expect(ids).toContain('idea');
  });

  it('gradient is a valid tailwind class string', () => {
    defaultRecommendations.forEach((rec) => {
      expect(rec.gradient).toMatch(/^bg-gradient-to-/);
    });
  });
});
