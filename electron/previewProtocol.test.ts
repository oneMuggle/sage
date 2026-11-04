// electron/previewProtocol.test.ts
//
// 预览协议纯函数测试 —— 只覆盖不依赖 Electron 注册表接口的部分。
// registerPreviewScheme / registerPreviewProtocol / registerPreviewIpc
// 依赖主进程上下文，由 smoke / e2e 覆盖；此处只测数据面。
import { describe, it, expect, beforeEach } from 'vitest';

import {
  PREVIEW_SCHEME,
  clearPreviews,
  getPreviewHtml,
  parsePreviewUrl,
  publishPreview,
  revokePreview,
} from './previewProtocol';

describe('sage-preview:// 数据面', () => {
  beforeEach(() => {
    clearPreviews();
  });

  it('publish 返回随机 id 与 sage-preview:// 可加载 URL', () => {
    const result = publishPreview('<p>hello</p>');
    expect(result.id).toMatch(/^[0-9a-f-]+$/i);
    expect(result.url).toBe(`${PREVIEW_SCHEME}://${result.id}/index.html`);
    expect(getPreviewHtml(result.id)).toBe('<p>hello</p>');
  });

  it('revoke 清除注册表条目', () => {
    const { id } = publishPreview('<p>gone</p>');
    expect(getPreviewHtml(id)).toBeDefined();
    revokePreview(id);
    expect(getPreviewHtml(id)).toBeUndefined();
  });

  it('revoke 不存在的 id 不抛错', () => {
    expect(() => revokePreview('not-an-id')).not.toThrow();
  });

  it('空字符串也允许发布（预览层自己处理空内容）', () => {
    const { id } = publishPreview('');
    expect(getPreviewHtml(id)).toBe('');
  });

  it('注册表超过 MAX_PREVIEWS 淘汰最早发布的条目', () => {
    const ids: string[] = [];
    for (let i = 0; i < 40; i++) {
      ids.push(publishPreview(`<p>html-${i}</p>`).id);
    }
    // 最早的若干条应已被淘汰（MAX_PREVIEWS = 32）
    expect(getPreviewHtml(ids[0])).toBeUndefined();
    expect(getPreviewHtml(ids[7])).toBeUndefined();
    // 最新的几条保留
    expect(getPreviewHtml(ids[39])).toBe('<p>html-39</p>');
    expect(getPreviewHtml(ids[38])).toBe('<p>html-38</p>');
  });

  it('clearPreviews 清空注册表', () => {
    publishPreview('a');
    publishPreview('b');
    clearPreviews();
    const after = publishPreview('c');
    expect(getPreviewHtml(after.id)).toBe('c');
  });

  it('parsePreviewUrl 接受合法 sage-preview:// URL', () => {
    const parsed = parsePreviewUrl('sage-preview://abc-def/index.html');
    expect(parsed).toEqual({ id: 'abc-def', path: '/index.html' });
  });

  it('parsePreviewUrl 接受根路径', () => {
    expect(parsePreviewUrl('sage-preview://xyz/')).toEqual({ id: 'xyz', path: '/' });
  });

  it('parsePreviewUrl 拒绝非本协定的 URL', () => {
    expect(parsePreviewUrl('https://example.com/foo')).toBeNull();
    expect(parsePreviewUrl('file:///etc/passwd')).toBeNull();
    expect(parsePreviewUrl('http://sage-preview/abc')).toBeNull();
  });

  it('parsePreviewUrl 拒绝空 hostname（防 SSRF 越权）', () => {
    expect(parsePreviewUrl('sage-preview:///index.html')).toBeNull();
  });

  it('parsePreviewUrl 拒绝无法解析的字符串', () => {
    expect(parsePreviewUrl('not a url at all')).toBeNull();
    expect(parsePreviewUrl('')).toBeNull();
  });
});
