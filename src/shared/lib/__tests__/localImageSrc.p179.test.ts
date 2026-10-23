import { describe, expect, it } from 'vitest';

import {
  auditLocalImageSrcGovernance,
  buildLocalImageSrc,
  formatLocalImageSrcJson,
  formatLocalImageSrcSummary,
} from '../localImageSrc';

describe('localImageSrc P179 governance audit', () => {
  it('audits localImageSrc governance contract and sage-file URL resolution', () => {
    const raw = auditLocalImageSrcGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.lib.local_image_src.governance.v1');
    expect(parsed.phase).toBe('P179');
    expect(parsed.protocolPrefix).toBe('sage-file://p/');
    expect(buildLocalImageSrc('https://example.com/a.png', '/ws')).toBe(
      'https://example.com/a.png',
    );
    expect(formatLocalImageSrcSummary('a.png', '/ws')).toContain('sage-file ·');
    expect(JSON.parse(formatLocalImageSrcJson('a.png', '/ws')).isSageFile).toBe(true);
  });
});
