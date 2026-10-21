// src/features/artifacts/__tests__/artifactListStore.test.ts
//
// right-panel R1 批次 A: 产物列表 store —— 按会话缓存、inflight 去重、
// 失败保留旧值、clear 防泄漏。

import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../artifactApi', () => ({
  listArtifacts: vi.fn(),
}));

import { listArtifacts, type Artifact } from '../artifactApi';
import {
  buildArtifactListStoreAuditJson,
  buildArtifactListStoreAuditSnapshot,
  useArtifactListStore,
} from '../artifactListStore';

const mockedList = vi.mocked(listArtifacts);

const art = (id: string): Artifact => ({
  id,
  session_id: 's1',
  tool_call_id: null,
  path: `/tmp/${id}`,
  name: id,
  kind: 'text',
  size: 1,
  created_at: 1,
});

beforeEach(() => {
  mockedList.mockReset();
  useArtifactListStore.setState({ bySession: {} });
});

describe('artifactListStore', () => {
  it('fetch 拉取并按会话缓存', async () => {
    mockedList.mockResolvedValue([art('a1')]);
    await useArtifactListStore.getState().fetch('s1');
    expect(useArtifactListStore.getState().bySession['s1']).toHaveLength(1);
    expect(mockedList).toHaveBeenCalledWith('s1');
  });

  it('并发 fetch 合并为一次请求（inflight 去重）', async () => {
    mockedList.mockImplementation(() => new Promise((res) => setTimeout(() => res([art('a1')]), 10)));
    const p1 = useArtifactListStore.getState().fetch('s1');
    const p2 = useArtifactListStore.getState().fetch('s1');
    await Promise.all([p1, p2]);
    expect(mockedList).toHaveBeenCalledTimes(1);
  });

  it('失败保留旧列表不崩溃', async () => {
    mockedList.mockResolvedValueOnce([art('old')]);
    await useArtifactListStore.getState().fetch('s1');
    mockedList.mockRejectedValueOnce(new Error('network'));
    await useArtifactListStore.getState().fetch('s1');
    expect(useArtifactListStore.getState().bySession['s1']).toHaveLength(1);
  });

  it('clear 移除指定会话', async () => {
    mockedList.mockResolvedValue([art('a1')]);
    await useArtifactListStore.getState().fetch('s1');
    useArtifactListStore.getState().clear('s1');
    expect(useArtifactListStore.getState().bySession['s1']).toBeUndefined();
  });

  it('exports artifactListStore audit snapshot and JSON helpers', () => {
    expect(buildArtifactListStoreAuditSnapshot()).toBe(
      'sessions:0|total:0|active:none|activeCount:0',
    );
    expect(
      buildArtifactListStoreAuditSnapshot({
        sessionCount: 2,
        totalArtifacts: 5,
        activeSessionId: 's1',
        activeSessionCount: 3,
      }),
    ).toBe('sessions:2|total:5|active:s1|activeCount:3');

    const parsed = JSON.parse(
      buildArtifactListStoreAuditJson({
        sessionCount: 1,
        totalArtifacts: 2,
        activeSessionId: 's1',
        activeSessionCount: 2,
      }),
    );
    expect(parsed).toEqual({
      sessionCount: 1,
      totalArtifacts: 2,
      activeSessionId: 's1',
      activeSessionCount: 2,
      snapshot: 'sessions:1|total:2|active:s1|activeCount:2',
    });
  });
});
