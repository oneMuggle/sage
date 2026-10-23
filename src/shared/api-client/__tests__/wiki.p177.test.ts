import { describe, expect, it } from 'vitest';

import {
  auditWikiApiClientGovernance,
  formatWikiApiClientJson,
  formatWikiApiClientSummary,
  WIKI_API_BASE,
} from '../wiki';

describe('wiki api-client P177 governance audit', () => {
  it('audits wiki API client governance contract and formatters', () => {
    const raw = auditWikiApiClientGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.api_client.wiki.governance.v1');
    expect(parsed.phase).toBe('P177');
    expect(parsed.baseUrl).toBe(WIKI_API_BASE);
    expect(formatWikiApiClientSummary(false, 20)).toContain('defaultLimit=20');
    expect(JSON.parse(formatWikiApiClientJson(false, 20)).defaultSearchLimit).toBe(20);
  });
});
