import { describe, expect, it } from 'vitest';

import {
  buildTaskTree,
  formatTaskTreeSummary,
  formatTaskTreeJson,
} from '../taskTree';

describe('taskTree audit helpers', () => {
  it('builds task tree and formats summary and json snapshot', () => {
    const tree = buildTaskTree([
      { task_id: 't1', agent_id: 'agent-1', goal: 'Root task' },
      { task_id: 't2', agent_id: 'agent-2', goal: 'Child task', parent_task_id: 't1' },
    ]);
    expect(formatTaskTreeSummary(tree)).toBe('nodes=2 · roots=1 · maxDepth=1');
    const parsed = JSON.parse(formatTaskTreeJson(tree));
    expect(parsed).toEqual({
      nodeCount: 2,
      rootCount: 1,
      maxDepth: 1,
      roots: ['t1'],
    });
  });

  it('handles empty or nullish tree index safely', () => {
    expect(formatTaskTreeSummary(null)).toBe('nodes=0 · roots=0 · maxDepth=0');
    expect(JSON.parse(formatTaskTreeJson(undefined)).nodeCount).toBe(0);
  });
});
