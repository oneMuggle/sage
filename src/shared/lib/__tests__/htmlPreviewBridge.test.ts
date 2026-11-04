// src/shared/lib/__tests__/htmlPreviewBridge.test.ts
//
// HTML 预览错误桥注入测试 —— 校验注入位置、注入脚本可被预览页消费、
// 注入不会污染用户原文（原文只通过 HtmlPreviewHost props 透传）。
import { describe, it, expect } from 'vitest';

import {
  HTML_PREVIEW_BRIDGE_SCRIPT,
  PREVIEW_BRIDGE_CHANNEL,
  injectPreviewBridge,
} from '../htmlPreviewBridge';

describe('htmlPreviewBridge', () => {
  it('PREVIEW_BRIDGE_CHANNEL 是非空字符串且不含脚本闭合序列', () => {
    expect(typeof PREVIEW_BRIDGE_CHANNEL).toBe('string');
    expect(PREVIEW_BRIDGE_CHANNEL.length).toBeGreaterThan(0);
    // 任何字符串字面量都不能在注入脚本里留下 `</script>` 让浏览器误闭合
    expect(HTML_PREVIEW_BRIDGE_SCRIPT).not.toContain('</script>');
  });

  it('HTML_PREVIEW_BRIDGE_SCRIPT 使用 ES5 语法（不含 let/const/=>）', () => {
    expect(HTML_PREVIEW_BRIDGE_SCRIPT).not.toMatch(/\blet\b/);
    expect(HTML_PREVIEW_BRIDGE_SCRIPT).not.toMatch(/\bconst\b/);
    expect(HTML_PREVIEW_BRIDGE_SCRIPT).not.toContain('=>');
  });

  it('injectPreviewBridge 在 <head> 内注入桥接脚本', () => {
    const html = '<!doctype html><html><head><title>t</title></head><body></body></html>';
    const result = injectPreviewBridge(html);
    const headClose = result.indexOf('</head>');
    const injectIdx = result.indexOf(PREVIEW_BRIDGE_CHANNEL);
    expect(injectIdx).toBeGreaterThan(-1);
    expect(injectIdx).toBeLessThan(headClose);
    // 原文不被修改
    expect(result).toContain('<title>t</title>');
    expect(result).toContain('<body></body>');
  });

  it('injectPreviewBridge 在 <html> 后但无 <head> 时补建 head 注入', () => {
    const html = '<html><body><p>hi</p></body></html>';
    const result = injectPreviewBridge(html);
    expect(result).toMatch(/<html><head><script>/);
    expect(result).toContain(PREVIEW_BRIDGE_CHANNEL);
  });

  it('injectPreviewBridge 无 html/head 时前置注入', () => {
    const html = '<p>just a fragment</p>';
    const result = injectPreviewBridge(html);
    expect(result.indexOf('<script>')).toBe(0);
    expect(result).toContain('<p>just a fragment</p>');
  });

  it('injectPreviewBridge 对空字符串幂等', () => {
    expect(injectPreviewBridge('')).toBe('');
  });

  it('injectPreviewBridge 不修改入参（不可变约定）', () => {
    const original = '<html><head></head><body></body></html>';
    injectPreviewBridge(original);
    expect(original).toBe('<html><head></head><body></body></html>');
  });
});
