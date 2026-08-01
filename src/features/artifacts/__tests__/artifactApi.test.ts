// src/features/artifacts/__tests__/artifactApi.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { listArtifacts, readArtifactContent, revealArtifact } from '../artifactApi';

describe('artifactApi', () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it('listArtifacts returns artifacts array', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      json: async () => ({ artifacts: [{ id: 'a1', name: 'test.md', kind: 'markdown' }] }),
    });
    const result = await listArtifacts('sess_001');
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe('a1');
    expect(global.fetch).toHaveBeenCalledWith('/api/v1/sessions/sess_001/artifacts');
  });

  it('listArtifacts returns [] when artifacts missing', async () => {
    global.fetch = vi.fn().mockResolvedValue({ json: async () => ({}) });
    expect(await listArtifacts('s')).toEqual([]);
  });

  it('readArtifactContent fetches content endpoint', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      json: async () => ({ ok: true, kind: 'markdown', content: '# Hi', truncated: false }),
    });
    const result = await readArtifactContent('sess_001', 'a1');
    expect(result.content).toBe('# Hi');
    expect(global.fetch).toHaveBeenCalledWith('/api/v1/sessions/sess_001/artifacts/a1/content');
  });

  it('revealArtifact posts to reveal endpoint', async () => {
    global.fetch = vi.fn().mockResolvedValue({ json: async () => ({ ok: true }) });
    const result = await revealArtifact('sess_001', 'a1');
    expect(result.ok).toBe(true);
    expect(global.fetch).toHaveBeenCalledWith(
      '/api/v1/sessions/sess_001/artifacts/a1/reveal',
      expect.objectContaining({ method: 'POST' })
    );
  });
});
