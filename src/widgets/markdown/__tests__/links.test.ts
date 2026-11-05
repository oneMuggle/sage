// src/widgets/markdown/__tests__/links.test.ts
// isLocalFilePathHref + safeDecodeUri 单元测试（URL 编码修复 2026-11-03）
import { describe, expect, it } from 'vitest';

import { isLocalFilePathHref, safeDecodeUri } from '../links';

describe('safeDecodeUri', () => {
  it('解码中文 percent-encoding', () => {
    expect(safeDecodeUri('%E7%AE%97%E6%B3%95.md')).toBe('算法.md');
  });

  it('纯 ASCII 路径原样返回', () => {
    expect(safeDecodeUri('src/App.tsx')).toBe('src/App.tsx');
  });

  it('畸形 URI（裸 %）不抛错，原样返回', () => {
    expect(safeDecodeUri('100%done')).toBe('100%done');
  });

  it('混合路径：/ 保留 + 中文解码', () => {
    expect(safeDecodeUri('output/%E7%AE%97%E6%B3%95.md')).toBe('output/算法.md');
  });
});

describe('isLocalFilePathHref — URL 编码兼容', () => {
  it('原始中文路径 → true', () => {
    expect(isLocalFilePathHref('output/算法.md')).toBe(true);
  });

  it('percent-encoded 中文路径 → true（解码后判定）', () => {
    expect(isLocalFilePathHref('output/%E7%AE%97%E6%B3%95.md')).toBe(true);
  });

  it('encoded 裸文件名（带扩展名）→ true', () => {
    expect(isLocalFilePathHref('%E6%B5%8B%E8%AF%95.md')).toBe(true);
  });

  it('http 链接 → false（即使含编码字符）', () => {
    expect(isLocalFilePathHref('https://example.com/%E6%B5%8B%E8%AF%95')).toBe(false);
  });

  it('null/undefined/空字符串 → false', () => {
    expect(isLocalFilePathHref(null)).toBe(false);
    expect(isLocalFilePathHref(undefined)).toBe(false);
    expect(isLocalFilePathHref('')).toBe(false);
  });

  it('无路径特征也无扩展名 → false', () => {
    expect(isLocalFilePathHref('hello')).toBe(false);
  });
});
