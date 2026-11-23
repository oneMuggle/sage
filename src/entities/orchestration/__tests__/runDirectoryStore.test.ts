import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { DirectoryRun, RunDirectoryResponse } from '../../../shared/api/orchRunClient';
import { findActiveRunForSession, useRunDirectoryStore } from '../runDirectoryStore';

const listRunDirectory = vi.fn<(scope: string, limit: number) => Promise<RunDirectoryResponse>>();

vi.mock('../../../shared/api/orchRunClient', () => ({
  orchRunClient: {
    listRunDirectory: (scope: string, limit: number) => listRunDirectory(scope, limit),
  },
}));

const run = (over: Partial<DirectoryRun> = {}): DirectoryRun => ({
  run_id: 'orch-1',
  session_id: 's1',
  status: 'running',
  created_at: 900,
  dispatched_at: 950,
  confirmed_at: 940,
  original_request: '整理文献',
  final_summary: null,
  plan: [],
  tasks: [],
  ...over,
});

describe('runDirectoryStore', () => {
  beforeEach(() => {
    listRunDirectory.mockReset();
    useRunDirectoryStore.setState({ runs: [], generatedAt: null, loading: false, error: null });
  });

  it('refresh 成功写入 runs/generatedAt 并清空 error', async () => {
    listRunDirectory.mockResolvedValue({
      generated_at: 1763800000000,
      scope: 'all',
      runs: [run()],
    });

    await useRunDirectoryStore.getState().refresh();

    const state = useRunDirectoryStore.getState();
    expect(state.runs).toHaveLength(1);
    expect(state.generatedAt).toBe(1763800000000);
    expect(state.error).toBeNull();
    expect(listRunDirectory).toHaveBeenCalledWith('all', 50);
  });

  it('refresh 失败保留上一轮数据，只记录 error', async () => {
    useRunDirectoryStore.setState({ runs: [run()], generatedAt: 1 });
    listRunDirectory.mockRejectedValue(new Error('后端未就绪'));

    await useRunDirectoryStore.getState().refresh();

    const state = useRunDirectoryStore.getState();
    expect(state.runs).toHaveLength(1);
    expect(state.error).toBe('后端未就绪');
  });

  it('并发 refresh 去重：loading 期间不重复发请求', async () => {
    let resolve!: (value: RunDirectoryResponse) => void;
    listRunDirectory.mockReturnValue(new Promise((r) => (resolve = r)));

    const first = useRunDirectoryStore.getState().refresh();
    await useRunDirectoryStore.getState().refresh(); // loading 中直接返回
    resolve({ generated_at: 2, scope: 'all', runs: [] });
    await first;

    expect(listRunDirectory).toHaveBeenCalledTimes(1);
  });

  it('findActiveRunForSession 只匹配该会话的 running run', () => {
    const runs = [
      run({ run_id: 'orch-a', session_id: 's1', status: 'completed' }),
      run({ run_id: 'orch-b', session_id: 's1', status: 'running' }),
      run({ run_id: 'orch-c', session_id: 's2', status: 'running' }),
    ];
    expect(findActiveRunForSession(runs, 's1')?.run_id).toBe('orch-b');
    expect(findActiveRunForSession(runs, 's3')).toBeNull();
    expect(findActiveRunForSession(runs, null)).toBeNull();
  });
});
