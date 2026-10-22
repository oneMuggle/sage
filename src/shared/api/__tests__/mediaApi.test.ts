/**
 * mediaApi 单元测试——URL 解析和 blob 获取。
 */
import { describe, expect, it, vi } from 'vitest';

vi.stubGlobal('import', { meta: { env: { DEV: true } } });

import { formatMediaUrlJson, formatMediaUrlSummary, resolveMediaUrl } from '../mediaApi';

describe('mediaApi.resolveMediaUrl', () => {
  it('dev mode: URL unchanged (Vite proxy)', () => {
    const url = resolveMediaUrl('/api/v1/media/m1');
    expect(url).toBe('/api/v1/media/m1');
  });
});

describe('formatMediaUrlSummary / formatMediaUrlJson', () => {
  it('formats media URL resolution summary and JSON payload', () => {
    expect(formatMediaUrlSummary('/api/v1/media/m1', 'image/png')).toBe(
      'media-url: /api/v1/media/m1 · mime=image/png',
    );
    const payload = JSON.parse(formatMediaUrlJson('/api/v1/media/m1', 'image/png'));
    expect(payload).toEqual({
      apiUrl: '/api/v1/media/m1',
      resolvedUrl: '/api/v1/media/m1',
      mimeType: 'image/png',
      isBlobUrl: false,
    });
  });
});
