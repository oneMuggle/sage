import { describe, expect, it } from 'vitest';

import {
  formatLintStoreJson,
  formatLintStoreSummary,
  useLintStore,
} from '../lint-store';

describe('wiki lint-store audit helpers', () => {
  it('updates lint items and formats summary', () => {
    useLintStore.getState().reset();
    useLintStore.getState().addItem({
      id: 'lint-1',
      type: 'orphan',
      severity: 'warning',
      page: 'wiki/a.md',
      message: 'orphan page',
    });
    const state = useLintStore.getState();
    expect(formatLintStoreSummary(state.items, state.isLoading, state.error)).toBe(
      'status=idle · issues=1 · warnings=1',
    );
  });

  it('serializes lint store audit JSON', () => {
    expect(
      JSON.parse(formatLintStoreJson([], true, null)),
    ).toEqual({
      issueCount: 0,
      warningCount: 0,
      isLoading: true,
      error: null,
    });
  });
});
