import { describe, expect, it } from 'vitest';

import {
  auditBtwOverlayGovernance,
  BtwOverlay,
  formatBtwOverlayMarkdown,
} from '../BtwOverlay';

describe('BtwOverlay governance audit (P159)', () => {
  it('verifies BtwOverlay component and formatter availability', () => {
    const report = auditBtwOverlayGovernance();
    expect(report.module).toBe('features.chat.BtwOverlay');
    expect(report.phase).toBe('P159');
    expect(report.hasOverlayComponent).toBe(true);
    expect(report.hasJsonFormatter).toBe(true);
    expect(report.healthy).toBe(true);
    expect(typeof BtwOverlay).toBe('function');
  });

  it('formats BtwOverlay markdown snapshot', () => {
    const md = formatBtwOverlayMarkdown({
      question: 'sess-p159 question',
      answer: 'sess-p159 answer',
      isLoading: false,
    });
    expect(md).toContain('sess-p159');
  });
});
