/**
 * P9: 本地图片路径 → sage-file:// URL 转换。
 */
import { describe, expect, it } from 'vitest';

import { buildLocalImageSrc } from '../localImageSrc';

describe('buildLocalImageSrc', () => {
  it('Windows 绝对路径转 sage-file URL 并携带 ws', () => {
    const r = buildLocalImageSrc('C:\\ws\\img\\chart.png', 'C:\\workspaces\\demo');
    expect(r.startsWith('sage-file://p/')).toBe(true);
    expect(r).toContain(encodeURIComponent('C:/ws/img/chart.png'));
    expect(r).toContain(`ws=${encodeURIComponent('C:/workspaces/demo')}`);
  });

  it('POSIX 绝对路径转 sage-file URL', () => {
    const r = buildLocalImageSrc('/home/u/ws/pic.png', '/home/u/ws');
    expect(r.startsWith('sage-file://p/')).toBe(true);
  });

  it('相对路径基于工作区拼接', () => {
    const r = buildLocalImageSrc('./img/chart.png', '/home/u/ws');
    expect(r).toContain(encodeURIComponent('/home/u/ws/img/chart.png'));
  });

  it('无工作区时相对路径原样透传', () => {
    expect(buildLocalImageSrc('img/chart.png')).toBe('img/chart.png');
  });

  it('http/data/sage-file 与后端媒体路由原样透传', () => {
    expect(buildLocalImageSrc('https://x/a.png')).toBe('https://x/a.png');
    expect(buildLocalImageSrc('data:image/png;base64,xx')).toBe('data:image/png;base64,xx');
    expect(buildLocalImageSrc('sage-file://p/x')).toBe('sage-file://p/x');
    expect(buildLocalImageSrc('/api/v1/media/abc')).toBe('/api/v1/media/abc');
  });
});
