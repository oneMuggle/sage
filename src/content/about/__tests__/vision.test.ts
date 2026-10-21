import { describe, expect, it } from 'vitest';

import {
  formatVisionAuditJson,
  formatVisionAuditSummary,
  PHILOSOPHY,
  VISION,
} from '../vision';

describe('vision content', () => {
  it('exports non-empty VISION and 4 PHILOSOPHY principles', () => {
    expect(VISION).toContain('Sage');
    expect(PHILOSOPHY).toHaveLength(4);
  });

  it('formats vision audit summary and JSON (Phase P120)', () => {
    expect(formatVisionAuditSummary()).toContain('principles=4 · names=[记忆优先,渐进式自演化,透明可控,简单胜于复杂]');
    const parsed = JSON.parse(formatVisionAuditJson());
    expect(parsed.principleCount).toBe(4);
    expect(parsed.visionLength).toBe(VISION.length);
  });
});
