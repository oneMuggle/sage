import { describe, expect, it } from 'vitest';

import { auditTitlebarActionsGovernance } from '../TitlebarActions';

describe('TitlebarActions P150 governance audit', () => {
  it('returns healthy defaults for TitlebarActions governance', () => {
    const res = auditTitlebarActionsGovernance();
    expect(res.module).toBe('src/widgets/layout/TitlebarActions.tsx');
    expect(res.phase).toBe('P150');
    expect(res.actionCount).toBe(3);
    expect(res.searchAvailable).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when actionCount is 0 or searchAvailable is false', () => {
    const res = auditTitlebarActionsGovernance({
      actionCount: 0,
      searchAvailable: false,
    });
    expect(res.actionCount).toBe(0);
    expect(res.searchAvailable).toBe(false);
    expect(res.healthy).toBe(false);
  });
});
