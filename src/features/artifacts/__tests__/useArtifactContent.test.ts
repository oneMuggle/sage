// src/features/artifacts/__tests__/useArtifactContent.test.ts
import { renderHook, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../artifactApi', () => ({ readArtifactContent: vi.fn() }));

import { readArtifactContent } from '../artifactApi';
import { useArtifactContent } from '../useArtifactContent';

describe('useArtifactContent', () => {
  beforeEach(() => {
    vi.mocked(readArtifactContent).mockReset();
  });

  it('loads content when artifactId set', async () => {
    vi.mocked(readArtifactContent).mockResolvedValue({
      ok: true, kind: 'markdown', content: '# Hello', truncated: false,
    });
    const { result } = renderHook(() => useArtifactContent('sess_001', 'a1'));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.content?.content).toBe('# Hello');
  });

  it('clears content when artifactId null', () => {
    const { result } = renderHook(() => useArtifactContent('sess_001', null));
    expect(result.current.content).toBeNull();
    expect(result.current.loading).toBe(false);
    expect(readArtifactContent).not.toHaveBeenCalled();
  });
});
