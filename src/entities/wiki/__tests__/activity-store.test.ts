import { describe, expect, it } from 'vitest';

import {
  formatActivityStoreJson,
  formatActivityStoreSummary,
  useActivityStore,
} from '../activity-store';

describe('wiki activity-store audit helpers', () => {
  it('tracks activity items and formats summary', () => {
    useActivityStore.getState().clearItems();
    useActivityStore.getState().addItem({
      id: 'act-1',
      type: 'lint',
      status: 'running',
      startedAt: 1000,
    });
    const items = useActivityStore.getState().items;
    expect(formatActivityStoreSummary(items, 100)).toBe(
      'activities=1/100 · running=1 · errors=0',
    );
  });

  it('serializes activity store audit JSON', () => {
    expect(
      JSON.parse(
        formatActivityStoreJson(
          [{ id: 'act-2', type: 'ingest', status: 'error', startedAt: 2000 }],
          50,
        ),
      ),
    ).toEqual({
      total: 1,
      maxItems: 50,
      running: 0,
      errors: 1,
    });
  });
});
