import { beforeEach, describe, expect, it } from 'vitest';

import {
  getThinkingExpanded,
  setThinkingExpanded,
  thinkingExpansionKey,
} from '../thinkingExpansionStore';

describe('getThinkingExpanded', () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it('returns undefined when never set', () => {
    // Unique reasoning string → unique key; not touched by any other test.
    const key = thinkingExpansionKey('never-set-reasoning');
    expect(getThinkingExpanded(key)).toBeUndefined();
  });

  it('returns true after explicit expand', () => {
    const key = thinkingExpansionKey('expand-reasoning');
    setThinkingExpanded(key, true);
    expect(getThinkingExpanded(key)).toBe(true);
  });

  it('returns false after explicit collapse', () => {
    const key = thinkingExpansionKey('collapse-reasoning');
    setThinkingExpanded(key, false);
    expect(getThinkingExpanded(key)).toBe(false);
  });

  it('distinguishes explicit false from undefined', () => {
    const key = thinkingExpansionKey('false-vs-undefined-reasoning');
    expect(getThinkingExpanded(key)).toBeUndefined();
    setThinkingExpanded(key, false);
    expect(getThinkingExpanded(key)).toBe(false);
  });
});
