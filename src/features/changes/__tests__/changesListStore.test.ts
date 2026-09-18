// src/features/changes/__tests__/changesListStore.test.ts
//
// right-panel R3 批次 C: 变更列表 store —— 按会话缓存、inflight 去重、
// 错误友好化（workspace_not_bound）。

import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../shared/api/workspaceApi', () => ({
  workspaceApi: { getChanges: vi.fn() },
}));

import { workspaceApi } from '../../../shared/api/workspaceApi';
import { useChangesListStore } from '../changesListStore';

const mockGetChanges = vi.mocked(workspaceApi.getChanges);

const sample = {
  changes: [{ path: 'a.txt', indexStatus: 'M', worktreeStatus: 'M' }],
  clean: false,
  ahead: 0,
  behind: 0,
} as never;

beforeEach(() => {
  mockGetChanges.mockReset();
  useChangesListStore.setState({ bySession: {}, errors: {}, loadingBy: {} });
});

describe('changesListStore', () => {
  it('fetch 拉取并按会话缓存', async () => {
    mockGetChanges.mockResolvedValue(sample);
    await useChangesListStore.getState().fetch('s1');
    expect(useChangesListStore.getState().bySession['s1']).toBe(sample);
    expect(useChangesListStore.getState().errors['s1']).toBeNull();
  });

  it('并发 fetch 合并为一次请求', async () => {
    mockGetChanges.mockImplementation(
      () => new Promise((res) => setTimeout(() => res(sample), 10)),
    );
    const p1 = useChangesListStore.getState().fetch('s1');
    const p2 = useChangesListStore.getState().fetch('s1');
    await Promise.all([p1, p2]);
    expect(mockGetChanges).toHaveBeenCalledTimes(1);
  });

  it('workspace_not_bound 错误转为友好文案', async () => {
    mockGetChanges.mockRejectedValue(new Error('workspace_not_bound: bind first'));
    await useChangesListStore.getState().fetch('s1');
    expect(useChangesListStore.getState().errors['s1']).toBe(
      '当前会话尚未绑定工作区，无法查看变更',
    );
  });

  it('clear 移除指定会话', async () => {
    mockGetChanges.mockResolvedValue(sample);
    await useChangesListStore.getState().fetch('s1');
    useChangesListStore.getState().clear('s1');
    expect(useChangesListStore.getState().bySession['s1']).toBeUndefined();
  });
});
