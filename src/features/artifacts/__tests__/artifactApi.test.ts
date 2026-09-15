// src/features/artifacts/__tests__/artifactApi.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest';

import {
  listArtifacts,
  listArtifactVersions,
  getArtifactVersion,
  readArtifactContent,
  restoreArtifactVersion,
  revealArtifact,
  updateArtifactContent,
} from '../artifactApi';

describe('artifactApi', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    (window as unknown as { electronAPI: unknown }).electronAPI = {
      backendRequest: async (request: {
        path: string;
        method?: string;
        headers?: HeadersInit;
        body?: unknown;
      }) => {
        const response = await global.fetch(request.path, {
          method: request.method,
          headers: request.headers,
          body: request.body === undefined ? undefined : JSON.stringify(request.body),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText ?? ''}`);
        return response.json();
      },
    };
  });

  it('listArtifacts returns artifacts array', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ artifacts: [{ id: 'a1', name: 'test.md', kind: 'markdown' }] }),
    });
    const result = await listArtifacts('sess_001');
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe('a1');
    expect(global.fetch).toHaveBeenCalledWith(
      '/api/v1/sessions/sess_001/artifacts',
      expect.anything(),
    );
  });

  it('listArtifacts returns [] when artifacts missing', async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({}) });
    expect(await listArtifacts('s')).toEqual([]);
  });

  it('listArtifacts rejects on non-ok response', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
    });
    await expect(listArtifacts('s')).rejects.toThrow(/500/);
    await expect(listArtifacts('s')).rejects.toThrow(/listArtifacts failed/);
  });

  it('readArtifactContent fetches content endpoint', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ ok: true, kind: 'markdown', content: '# Hi', truncated: false }),
    });
    const result = await readArtifactContent('sess_001', 'a1');
    expect(result.content).toBe('# Hi');
    expect(global.fetch).toHaveBeenCalledWith(
      '/api/v1/sessions/sess_001/artifacts/a1/content',
      expect.anything(),
    );
  });

  it('readArtifactContent rejects on non-ok response', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
    });
    await expect(readArtifactContent('s', 'a1')).rejects.toThrow(/500/);
    await expect(readArtifactContent('s', 'a1')).rejects.toThrow(/readArtifactContent failed/);
  });

  it('revealArtifact posts to reveal endpoint', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ ok: true }),
    });
    const result = await revealArtifact('sess_001', 'a1');
    expect(result.ok).toBe(true);
    expect(global.fetch).toHaveBeenCalledWith(
      '/api/v1/sessions/sess_001/artifacts/a1/reveal',
      expect.objectContaining({ method: 'POST' }),
    );
  });
});

// ==================== Version History (Phase 2 M2) ====================

describe('artifactApi - version history', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    (window as unknown as { electronAPI: unknown }).electronAPI = {
      backendRequest: async (request: {
        path: string;
        method?: string;
        headers?: HeadersInit;
        body?: unknown;
      }) => {
        const response = await global.fetch(request.path, {
          method: request.method,
          headers: request.headers,
          body: request.body === undefined ? undefined : JSON.stringify(request.body),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText ?? ''}`);
        return response.json();
      },
    };
  });

  describe('listArtifactVersions', () => {
    it('returns version metadata array', async () => {
      const versions = [
        {
          artifact_id: 'a1',
          version_num: 2,
          content_hash: 'h2',
          snapshot_path: '/p/v2.txt',
          created_at: 2000,
          note: 'edit',
        },
        {
          artifact_id: 'a1',
          version_num: 1,
          content_hash: 'h1',
          snapshot_path: '/p/v1.txt',
          created_at: 1000,
          note: 'initial',
        },
      ];
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ versions }),
      });

      const result = await listArtifactVersions('sess_001', 'a1');

      expect(result).toHaveLength(2);
      expect(result[0].version_num).toBe(2);
      expect(result[1].version_num).toBe(1);
      expect(global.fetch).toHaveBeenCalledWith(
        '/api/v1/sessions/sess_001/artifacts/a1/versions',
        expect.anything(),
      );
    });

    it('returns empty array when no versions', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ versions: [] }),
      });
      expect(await listArtifactVersions('s', 'a1')).toEqual([]);
    });

    it('rejects on non-ok response', async () => {
      global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 404, statusText: 'Not Found' });
      await expect(listArtifactVersions('s', 'missing')).rejects.toThrow(/404/);
    });
  });

  describe('getArtifactVersion', () => {
    it('returns version with content', async () => {
      const version = {
        artifact_id: 'a1',
        version_num: 1,
        content_hash: 'h1',
        snapshot_path: '/p/v1.txt',
        created_at: 1000,
        note: 'initial',
        content: '# Version 1\n',
      };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => version,
      });

      const result = await getArtifactVersion('sess_001', 'a1', 1);

      expect(result.version_num).toBe(1);
      expect(result.content).toBe('# Version 1\n');
      expect(global.fetch).toHaveBeenCalledWith(
        '/api/v1/sessions/sess_001/artifacts/a1/versions/1',
        expect.anything(),
      );
    });

    it('rejects on 404', async () => {
      global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 404, statusText: 'Not Found' });
      await expect(getArtifactVersion('s', 'a1', 999)).rejects.toThrow(/404/);
    });
  });

  describe('restoreArtifactVersion', () => {
    it('posts restore and returns new version', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          restored_from: 1,
          new_version: {
            artifact_id: 'a1',
            version_num: 3,
            content_hash: 'h3',
            snapshot_path: '/p/v3.txt',
            created_at: 3000,
            note: 'restore',
          },
        }),
      });

      const result = await restoreArtifactVersion('sess_001', 'a1', 1, 'restore');

      expect(result.restored_from).toBe(1);
      expect(result.new_version.version_num).toBe(3);
      expect(global.fetch).toHaveBeenCalledWith(
        '/api/v1/sessions/sess_001/artifacts/a1/versions/restore',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ version_num: 1, note: 'restore' }),
        }),
      );
    });

    it('uses default note "restore" when omitted', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ restored_from: 1, new_version: { version_num: 2 } }),
      });

      await restoreArtifactVersion('sess_001', 'a1', 1);

      expect(global.fetch).toHaveBeenCalledWith(
        '/api/v1/sessions/sess_001/artifacts/a1/versions/restore',
        expect.objectContaining({
          body: JSON.stringify({ version_num: 1, note: 'restore' }),
        }),
      );
    });
  });

  describe('updateArtifactContent', () => {
    it('puts new content with base_hash and returns version', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          version: {
            artifact_id: 'a1',
            version_num: 2,
            content_hash: 'newh',
            snapshot_path: '/p/v2.txt',
            created_at: 2000,
            note: 'edit',
          },
        }),
      });

      const result = await updateArtifactContent('sess_001', 'a1', 'basehash', '# New\n', 'edit');

      expect(result.version.version_num).toBe(2);
      expect(global.fetch).toHaveBeenCalledWith(
        '/api/v1/sessions/sess_001/artifacts/a1',
        expect.objectContaining({
          method: 'PUT',
          body: JSON.stringify({ base_hash: 'basehash', content: '# New\n', note: 'edit' }),
        }),
      );
    });

    it('uses default note "edit" when omitted', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ version: { version_num: 2 } }),
      });

      await updateArtifactContent('sess_001', 'a1', 'bh', 'content');

      expect(global.fetch).toHaveBeenCalledWith(
        '/api/v1/sessions/sess_001/artifacts/a1',
        expect.objectContaining({
          body: JSON.stringify({ base_hash: 'bh', content: 'content', note: 'edit' }),
        }),
      );
    });

    it('rejects on 409 Conflict', async () => {
      global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 409, statusText: 'Conflict' });
      await expect(updateArtifactContent('s', 'a1', 'wrong', 'x')).rejects.toThrow(/409/);
    });
  });
});
