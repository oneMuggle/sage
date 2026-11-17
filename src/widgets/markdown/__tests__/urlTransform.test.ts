/**
 * Markdown URL 消毒白名单单测（2026-11-15）。
 *
 * pdf-figure-citation：图片源需要放行 data:image / sage-file / Windows 盘符
 * 路径，同时 javascript: 等危险协议必须继续拦截。
 */
import { describe, expect, it } from 'vitest';

import { safeUrlTransform } from '../links';

const NODE = null as never;

describe('safeUrlTransform', () => {
  it('放行 data:image 图片源', () => {
    const url = 'data:image/png;base64,AAAA';
    expect(safeUrlTransform(url, 'src', NODE)).toBe(url);
  });

  it('拦截非图片 data: 源', () => {
    expect(safeUrlTransform('data:text/html,<script>', 'src', NODE)).toBe('');
  });

  it('放行 Windows 盘符路径', () => {
    expect(safeUrlTransform('C:\\workspace\\fig.png', 'src', NODE)).toBe('C:\\workspace\\fig.png');
    expect(safeUrlTransform('C:/workspace/fig.png', 'src', NODE)).toBe('C:/workspace/fig.png');
  });

  it('放行应用内绝对路径与 sage-file', () => {
    expect(safeUrlTransform('/api/v1/media/abc123', 'src', NODE)).toBe('/api/v1/media/abc123');
    expect(safeUrlTransform('sage-file://p/%2Fws%2Fa.png', 'src', NODE)).toBe(
      'sage-file://p/%2Fws%2Fa.png',
    );
  });

  it('拦截 javascript 图片源', () => {
    expect(safeUrlTransform('javascript:alert(1)', 'src', NODE)).toBe('');
  });

  it('链接沿用 react-markdown 默认白名单', () => {
    expect(safeUrlTransform('javascript:alert(1)', 'href', NODE)).toBe('');
    expect(safeUrlTransform('https://example.com/a', 'href', NODE)).toBe('https://example.com/a');
  });
});
