// src/features/artifacts/__tests__/useArtifacts.test.ts
import { renderHook, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../artifactApi', () => ({ listArtifacts: vi.fn() }));

import { listArtifacts } from '../artifactApi';
import { useArtifacts } from '../useArtifacts';

const mkArt = (id: string) => ({
  id, session_id: 's', tool_call_id: null, path: `/${id}.md`, name: `${id}.md`,
  kind: 'markdown' as const, size: 1, created_at: 1,
});

describe('useArtifacts', () => {
  beforeEach(() => {
    vi.mocked(listArtifacts).mockReset();
  });

  it('loads artifacts on mount', async () => {
    vi.mocked(listArtifacts).mockResolvedValue([mkArt('a1')]);
    const { result } = renderHook(() => useArtifacts('sess_001'));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.artifacts).toHaveLength(1);
  });

  it('does not load when sessionId is null', () => {
    const { result } = renderHook(() => useArtifacts(null));
    expect(result.current.artifacts).toEqual([]);
    expect(result.current.loading).toBe(false);
    expect(listArtifacts).not.toHaveBeenCalled();
  });

  it('refresh refetches', async () => {
    vi.mocked(listArtifacts).mockResolvedValue([mkArt('a1')]);
    const { result } = renderHook(() => useArtifacts('sess_001'));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(listArtifacts).toHaveBeenCalledTimes(1);
    result.current.refresh();
    await waitFor(() => expect(listArtifacts).toHaveBeenCalledTimes(2));
  });
});
