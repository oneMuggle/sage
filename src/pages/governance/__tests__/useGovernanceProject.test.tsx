import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { list, update, updateAllowedPaths } = vi.hoisted(() => ({
  list: vi.fn(),
  update: vi.fn(),
  updateAllowedPaths: vi.fn(),
}));

vi.mock('../../../shared/api', async () => {
  const actual = await vi.importActual<typeof import('../../../shared/api')>('../../../shared/api');
  return {
    ...actual,
    projectApi: {
      ...actual.projectApi,
      list,
      update,
      updateAllowedPaths,
      listMilestones: vi.fn().mockResolvedValue([]),
    },
    memoryApi: { ...actual.memoryApi, getProjectProfile: vi.fn().mockResolvedValue({ items: [] }) },
  };
});

import { computeBootstrapProgress, useGovernanceProject } from '../useGovernanceProject';

const PROJECT = {
  id: 'p-1',
  name: 'Sage',
  path: '/w/sage',
  createdAt: 1,
  lastOpenedAt: 2,
  sessionCount: 0,
  lastSessionId: null,
  allowedPaths: ['/w/shared/**'],
  projectType: null,
  detectedType: 'research',
  vcsMode: 'builtin',
  bootstrapState: { applied: ['sage_md', 'rule'], appliedAt: 1 },
};

beforeEach(() => {
  vi.clearAllMocks();
  list.mockResolvedValue([PROJECT]);
});

describe('computeBootstrapProgress', () => {
  it('counts applied steps', () => {
    const progress = computeBootstrapProgress(PROJECT as never);
    expect(progress.total).toBe(5);
    expect(progress.done).toBe(2);
    expect(progress.steps.find((s) => s.id === 'sage_md')?.done).toBe(true);
  });
});

describe('useGovernanceProject', () => {
  it('loads the project and falls back to detectedType', async () => {
    const { result } = renderHook(() => useGovernanceProject('p-1'));
    await waitFor(() => expect(result.current.project?.id).toBe('p-1'));
    expect(result.current.activeProjectType).toBe('research');
  });

  it('resets stage to the first blueprint stage when type changes', async () => {
    update.mockImplementation((_id: string, patch: Record<string, unknown>) =>
      Promise.resolve({ ...PROJECT, ...patch, projectType: patch.project_type }),
    );
    const { result } = renderHook(() => useGovernanceProject('p-1'));
    await waitFor(() => expect(result.current.project).not.toBeNull());
    await act(() => result.current.changeProjectType('coding'));
    expect(update).toHaveBeenCalledWith('p-1', expect.objectContaining({ project_type: 'coding' }));
    expect(result.current.project?.projectType).toBe('coding');
  });

  it('ignores duplicate allowed paths', async () => {
    const { result } = renderHook(() => useGovernanceProject('p-1'));
    await waitFor(() => expect(result.current.project).not.toBeNull());
    await act(() => result.current.quickAddPresetPath('/w/shared/**'));
    expect(updateAllowedPaths).not.toHaveBeenCalled();
  });
});
