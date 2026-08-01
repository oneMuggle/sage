// src/features/artifacts/__tests__/useArtifactContent.rejection.test.ts
//
// Isolated single-test file for the error-resilience contract of
// useArtifactContent. Rationale (same as useArtifacts.rejection.test.ts): in
// this environment (Node 25 + vitest 1.6 + React act), a rejected mock combined
// with renderHook AND any other test in the same file triggers a spurious
// process-level error attribution ("Error: boom" attached to the test even
// though the hook's .catch swallows the failure). A single-test file with the
// identical body passes deterministically, so the rejection contract lives
// here, away from the happy-path suite.
import { renderHook, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

vi.mock('../artifactApi', () => ({ readArtifactContent: vi.fn() }));

import { useArtifactContent } from '../useArtifactContent';
import { readArtifactContent } from '../artifactApi';

describe('useArtifactContent error resilience', () => {
  it('does not crash and surfaces an error-shaped content when readArtifactContent rejects', async () => {
    vi.mocked(readArtifactContent).mockRejectedValue(new Error('boom'));
    const { result } = renderHook(() => useArtifactContent('sess_001', 'a1'));

    await waitFor(() => expect(result.current.loading).toBe(false));

    // hook must not crash; it converts the rejection into an error-shaped
    // content object so the viewer's existing error state can render it.
    expect(result.current.content).not.toBeNull();
    expect(result.current.content?.ok).toBe(false);
    expect(result.current.content?.error).toContain('boom');
  });
});
