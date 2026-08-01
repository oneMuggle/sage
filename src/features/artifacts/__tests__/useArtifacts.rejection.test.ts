// src/features/artifacts/__tests__/useArtifacts.rejection.test.ts
//
// Isolated single-test file for the error-resilience contract of useArtifacts.
// Rationale: in this environment (Node 25 + vitest 1.6 + React act), a
// rejected mock combined with renderHook and ANY other test in the same file
// triggers a spurious process-level error attribution ("Error: boom" attached
// to the test even though the hook's catch swallows the failure). A
// single-test file with the identical body passes deterministically, so the
// rejection contract lives here, away from the happy-path suite.
import { renderHook, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

vi.mock('../artifactApi', () => ({ listArtifacts: vi.fn() }));

import { useArtifacts } from '../useArtifacts';
import { listArtifacts } from '../artifactApi';

const mkArt = (id: string) => ({
  id, session_id: 's', tool_call_id: null, path: `/${id}.md`, name: `${id}.md`,
  kind: 'markdown' as const, size: 1, created_at: 1,
});

describe('useArtifacts error resilience', () => {
  it('does not throw and keeps previous artifacts when listArtifacts rejects', async () => {
    vi.mocked(listArtifacts).mockResolvedValue([mkArt('a1')]);
    const { result } = renderHook(() => useArtifacts('sess_001'));
    await waitFor(() => expect(result.current.artifacts).toHaveLength(1));

    vi.mocked(listArtifacts).mockRejectedValue(new Error('boom'));
    let threw = false;
    try {
      await result.current.refresh();
    } catch {
      threw = true;
    }

    expect(threw).toBe(false);
    expect(result.current.loading).toBe(false);
    // transient failure must not blank a previously-loaded list
    expect(result.current.artifacts).toEqual([mkArt('a1')]);
  });
});
