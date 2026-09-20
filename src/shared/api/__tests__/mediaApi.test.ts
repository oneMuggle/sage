/**
 * mediaApi 单元测试——URL 解析和 blob 获取。
 */
import { describe, expect, it, vi } from 'vitest';

vi.stubGlobal('import', { meta: { env: { DEV: true } } });

import { resolveMediaUrl } from '../mediaApi';

describe('mediaApi.resolveMediaUrl', () => {
  it('dev mode: URL unchanged (Vite proxy)', () => {
    const url = resolveMediaUrl('/api/v1/media/m1');
    expect(url).toBe('/api/v1/media/m1');
  });
});
