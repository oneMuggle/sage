import { describe, expect, it } from 'vitest';

import { getEntityKindSuggestions, parseEntityRefQuery } from '../entityRefs';

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
