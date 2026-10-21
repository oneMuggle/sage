import { describe, expect, it } from 'vitest';

import {
  buildEntityRefsAuditJson,
  buildEntityRefsAuditSnapshot,
  getEntityKindSuggestions,
  parseEntityRefQuery,
} from '../entityRefs';

describe('entityRefs helpers', () => {
  it('suggests all kinds for empty query', () => {
    expect(getEntityKindSuggestions('').map((s) => s.kind)).toEqual([
      'memory',
      'wiki',
      'skill',
      'agent',
    ]);
  });

  it('filters by prefix case-insensitively', () => {
    expect(getEntityKindSuggestions('Me').map((s) => s.token)).toEqual(['@memory:']);
    expect(getEntityKindSuggestions('s').map((s) => s.kind)).toEqual(['skill']);
  });

  it('returns nothing once a colon/path is typed or for null', () => {
    expect(getEntityKindSuggestions('memory:foo')).toEqual([]);
    expect(getEntityKindSuggestions('src/a')).toEqual([]);
    expect(getEntityKindSuggestions(null)).toEqual([]);
    expect(getEntityKindSuggestions('zzz')).toEqual([]);
  });

  it('parses entity ref queries', () => {
    expect(parseEntityRefQuery('wiki:量子')).toEqual({ kind: 'wiki', query: '量子' });
    expect(parseEntityRefQuery('agent:')).toEqual({ kind: 'agent', query: '' });
    expect(parseEntityRefQuery('src/foo.ts')).toBeNull();
    expect(parseEntityRefQuery(null)).toBeNull();
  });
});

describe('entityRefs governance audit helpers (Phase P107)', () => {
  it('builds deterministic audit snapshot and JSON for null, prefix, and entity-mode queries', () => {
    const nullSnap = buildEntityRefsAuditSnapshot(null);
    expect(nullSnap).toEqual({
      rawQuery: null,
      isEntityMode: false,
      parsedKind: null,
      parsedQuery: null,
      suggestionCount: 0,
      suggestedKinds: [],
      supportedKindCount: 4,
      signature: '-|0|-|-|0||4',
    });

    const entitySnap = buildEntityRefsAuditSnapshot('wiki:量子');
    expect(entitySnap).toEqual({
      rawQuery: 'wiki:量子',
      isEntityMode: true,
      parsedKind: 'wiki',
      parsedQuery: '量子',
      suggestionCount: 0,
      suggestedKinds: [],
      supportedKindCount: 4,
      signature: 'wiki:量子|1|wiki|量子|0||4',
    });
    expect(JSON.parse(buildEntityRefsAuditJson('wiki:量子'))).toEqual(entitySnap);
  });
});
