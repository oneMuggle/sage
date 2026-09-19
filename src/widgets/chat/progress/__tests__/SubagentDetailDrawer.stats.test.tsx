// @vitest-environment jsdom
/**
 * RD19 (round35): SubagentDetailDrawer 消耗/时长统计行。
 *
 * selectTask meta（来自聊天任务板终态事件）→ Drawer 头部渲染
 * `drawer-task-stats`；无 meta / 全零时不渲染。
 */
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { useRunControlStore } from '../../../../entities/orchestration/runControlStore';
import type { RunSnapshot } from '../../../../shared/api/orchEvents';
import { SubagentDetailDrawer } from '../SubagentDetailDrawer';

function seedRun(): void {
  const snapshot: RunSnapshot = {
    run_id: 'orch-rd19',
    status: 'running',
    summary: { total: 1 },
    last_event_seq: 1,
    updated_at: Date.now(),
    tasks: [
      {
        task_id: 't1',
        agent_id: 'primary',
        status: 'running',
        current_step_id: null,
        output_preview: null,
        error: null,
      },
    ],
  };
  useRunControlStore.setState((prev) => {
    const runs = new Map(prev.runs);
    runs.set('orch-rd19', snapshot);
    return { runs } as typeof prev;
  });
  useRunControlStore.getState().selectTask('orch-rd19', 't1');
}

describe('SubagentDetailDrawer — 任务级统计 (RD19)', () => {
  beforeEach(() => {
    seedRun();
  });

  it('meta 有消耗/时长 → 渲染 drawer-task-stats', () => {
    useRunControlStore.getState().selectTask('orch-rd19', 't1', {
      used_tokens: 4200,
      duration_ms: 2500,
    });
    render(<SubagentDetailDrawer open onClose={() => {}} />);
    const stats = screen.getByTestId('drawer-task-stats');
    expect(stats.textContent).toContain('4,200 tokens');
    expect(stats.textContent).toContain('时长 2s'); // 2500ms → floor 2s
  });

  it('无 meta → 不渲染统计行', () => {
    useRunControlStore.getState().selectTask('orch-rd19', 't1', null);
    render(<SubagentDetailDrawer open onClose={() => {}} />);
    expect(screen.queryByTestId('drawer-task-stats')).toBeNull();
  });
});
