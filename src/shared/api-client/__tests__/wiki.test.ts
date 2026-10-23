import { describe, expect, it } from 'vitest';

import {
  WIKI_API_BASE,
  formatWikiApiClientJson,
  formatWikiApiClientSummary,
} from '../wiki';

describe('wiki API client audit diagnostics', () => {
  it('formats wiki API client summary', () => {
    expect(WIKI_API_BASE).toBe('http://127.0.0.1:8765/api/v1');
    expect(formatWikiApiClientSummary(false, 20)).toBe(
      'baseUrl=http://127.0.0.1:8765/api/v1 · demoBlocked=false · defaultLimit=20',
    );
    expect(formatWikiApiClientSummary(true, 10)).toBe(
      'baseUrl=http://127.0.0.1:8765/api/v1 · demoBlocked=true · defaultLimit=10',
    );
  });

  it('serializes wiki API client audit JSON', () => {
    const parsed = JSON.parse(formatWikiApiClientJson(false, 25));
    expect(parsed).toEqual({
      baseUrl: 'http://127.0.0.1:8765/api/v1',
      demoBlocked: false,
      defaultSearchLimit: 25,
    });
  });
});
