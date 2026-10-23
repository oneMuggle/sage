import { describe, expect, it } from 'vitest';

import {
  formatStudioStateJson,
  formatStudioStateSummary,
} from '../useStudioState';

describe('useStudioState audit helpers', () => {
  it('formats studio state summary', () => {
    expect(formatStudioStateSummary(4, 'proj-1', 'research', true)).toBe(
      'projects=4 · active=proj-1 · archetype=research · wizard=open',
    );
  });

  it('serializes studio state audit JSON', () => {
    expect(
      JSON.parse(formatStudioStateJson(2, null, 'coding', false)),
    ).toEqual({
      projectCount: 2,
      selectedProjectId: null,
      selectedArchetype: 'coding',
      wizardOpen: false,
    });
  });
});
