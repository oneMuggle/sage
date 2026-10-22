import { describe, expect, it } from 'vitest';

import { auditMarkdownImageGovernance } from '../MarkdownImage';

describe('MarkdownImage P150 governance audit', () => {
  it('returns healthy defaults for MarkdownImage governance', () => {
    const res = auditMarkdownImageGovernance();
    expect(res.module).toBe('src/widgets/chat/MarkdownImage.tsx');
    expect(res.phase).toBe('P150');
    expect(res.hasSrc).toBe(true);
    expect(res.lightboxEnabled).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when hasSrc is false', () => {
    const res = auditMarkdownImageGovernance({
      hasSrc: false,
      lightboxEnabled: false,
    });
    expect(res.hasSrc).toBe(false);
    expect(res.lightboxEnabled).toBe(false);
    expect(res.healthy).toBe(false);
  });
});
