import { describe, expect, it } from 'vitest';

import {
  formatResearchStoreJson,
  formatResearchStoreSummary,
  useResearchStore,
} from '../research-store';

describe('wiki research-store audit helpers', () => {
  it('manages research tasks and formats summary', () => {
    useResearchStore.getState().setTasks([]);
    useResearchStore.getState().addTask({
      id: 'res-1',
      topic: 'Graph RAG',
      status: 'done',
      webResults: [],
      synthesis: 'summary',
    });
    const state = useResearchStore.getState();
    expect(
      formatResearchStoreSummary(state.tasks, state.panelOpen, state.maxConcurrent),
    ).toBe('tasks=1 · done=1 · maxConcurrent=3 · panel=closed');
  });

  it('serializes research store audit JSON', () => {
    expect(JSON.parse(formatResearchStoreJson([], true, 5))).toEqual({
      taskCount: 0,
      doneCount: 0,
      panelOpen: true,
      maxConcurrent: 5,
    });
  });
});
