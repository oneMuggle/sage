import { describe, expect, it } from 'vitest';

import {
  formatQueueStoreJson,
  formatQueueStoreSummary,
  useQueueStore,
} from '../queue-store';

describe('wiki queue-store audit helpers', () => {
  it('resets store state and formats queue summary', () => {
    useQueueStore.getState().reset();
    expect(
      formatQueueStoreSummary(
        { pending: 2, processing: 1, completed: 5, failed: 0 },
        8,
        false,
      ),
    ).toBe(
      'tasks=8 · pending=2 · processing=1 · completed=5 · failed=0 · loading=false',
    );
  });

  it('serializes queue store audit JSON', () => {
    expect(
      JSON.parse(
        formatQueueStoreJson(
          { pending: 1, processing: 0, completed: 3, failed: 1, cancelled: 2 },
          7,
          true,
        ),
      ),
    ).toEqual({
      taskCount: 7,
      pending: 1,
      processing: 0,
      completed: 3,
      failed: 1,
      cancelled: 2,
      loading: true,
    });
  });
});
