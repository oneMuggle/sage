import { describe, expect, it } from 'vitest';

import { attentionView, newNeedsYouSessions } from '../engine/attentionView';

const ATTENTION = {
  needsYou: 2,
  failed: 1,
  running: 3,
  activeTasks: 1,
  total: 7,
  needsYouSessionIds: ['b', 'a'],
};

describe('attentionView', () => {
  it('shows the needs-you count with an alert ring', () => {
    const view = attentionView('acting', 'bash', 'Bash', ATTENTION);
    expect(view.count).toBe(2);
    expect(view.alert).toBe(true);
    expect(view.glyph).toBeTruthy();
    expect(view.title).toContain('2');
  });

  it('hides the badge when nothing needs the user', () => {
    const view = attentionView('idle', null, null, { ...ATTENTION, needsYou: 0 });
    expect(view.count).toBeNull();
    expect(view.alert).toBe(false);
  });

  it('tolerates a missing attention payload', () => {
    const view = attentionView('idle', null, null, undefined);
    expect(view.count).toBeNull();
    expect(view.alert).toBe(false);
  });

  it('caps the visible count at 99', () => {
    const view = attentionView('waiting', null, null, { ...ATTENTION, needsYou: 150 });
    expect(view.count).toBe(99);
  });
});

describe('newNeedsYouSessions', () => {
  it('returns only ids not seen before', () => {
    expect(newNeedsYouSessions(new Set(['a']), ['a', 'b', 'c'])).toEqual(['b', 'c']);
  });

  it('returns nothing when every id was seen', () => {
    expect(newNeedsYouSessions(new Set(['a', 'b']), ['a', 'b'])).toEqual([]);
  });
});
