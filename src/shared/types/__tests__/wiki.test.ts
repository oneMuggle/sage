import { describe, expect, it } from 'vitest';

import {
  formatWikiProjectJson,
  formatWikiProjectSummary,
} from '../wiki';

describe('wiki types audit diagnostics', () => {
  it('formats wiki project summary for bound and unbound projects', () => {
    expect(formatWikiProjectSummary(null, 2)).toBe('project=none · bound=false · recent=2');
    expect(
      formatWikiProjectSummary(
        { id: 'wk-1', name: 'Sage Docs', path: '/workspace/wiki' },
        5,
      ),
    ).toBe('project=wk-1 · bound=true · recent=5');
  });

  it('serializes wiki project audit JSON', () => {
    const parsed = JSON.parse(
      formatWikiProjectJson({ id: 'wk-2', name: 'Notes', path: '/notes' }, 3),
    );
    expect(parsed).toEqual({
      projectId: 'wk-2',
      name: 'Notes',
      path: '/notes',
      bound: true,
      recentCount: 3,
    });
  });
});
