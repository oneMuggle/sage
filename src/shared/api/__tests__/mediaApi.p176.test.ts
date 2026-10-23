import { describe, expect, it } from 'vitest';

import {
  auditMediaApiGovernance,
  formatMediaUrlJson,
  formatMediaUrlSummary,
} from '../mediaApi';

describe('mediaApi P176 governance audit', () => {
  it('audits mediaApi governance contract and media URL formatters', () => {
    const raw = auditMediaApiGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.api.media_api.governance.v1');
    expect(parsed.phase).toBe('P176');
    expect(parsed.supportsBlobFetch).toBe(true);
    expect(formatMediaUrlSummary('/api/v1/media/1', 'image/png')).toContain('/api/v1/media/1');
    expect(JSON.parse(formatMediaUrlJson('/api/v1/media/1', 'image/png')).apiUrl).toBe(
      '/api/v1/media/1',
    );
  });
});
