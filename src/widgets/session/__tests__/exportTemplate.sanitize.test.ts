/**
 * U18: 导出模板 sanitizeHtml 安全守卫(jsdom 级)
 *
 * template.js 是自包含 IIFE,无法 import 其内部纯函数。这里在 jsdom 里
 * 注入桩 marked(透传,模拟原始 HTML 直通)+ 桩 hljs,构造含恶意载荷的
 * 会话,执行整段模板,断言 sanitizeHtml 在真实渲染管线里:
 *  - 把 <meta http-equiv=refresh> 降级为文本(阻断自动跳转钓鱼,评审 M1);
 *  - 剥离 onerror / onload 等内联事件处理器(含 <svg/onload=> 无空格形态);
 *  - 注入脚本/处理器从不执行(window 哨兵保持 undefined)。
 *
 * 这是整个"base64 隔离 + CSP + 深度防御"设计的客户端侧回归守卫。
 */
// @vitest-environment jsdom
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

const here = dirname(fileURLToPath(import.meta.url));
const TEMPLATE_JS_PATH = resolve(
  here,
  '../../../../backend/application/services/export_assets/template.js',
);
const templateJs = readFileSync(TEMPLATE_JS_PATH, 'utf-8');

const HOSTILE =
  '<meta http-equiv="refresh" content="0;url=https://evil.example">' +
  '<img src=x onerror="window.__sagePwn=1">' +
  '<svg/onload="window.__sagePwn2=1">' +
  '正常文本';

function escHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function payloadBase64(userContent: string): string {
  const payload = {
    app: 'sage',
    exported_at: 1,
    header: { id: 's', title: 'sanitize 守卫', created_at: 1, updated_at: 1, total_tokens: 0, total_cost: 0 },
    entries: [
      {
        id: 'm1',
        role: 'user',
        content: userContent,
        created_at: 1,
        model: null,
        provider: null,
        tool_calls: [],
        tool_call_id: null,
        reasoning_content: '',
      },
    ],
    stats: { user_messages: 1, assistant_messages: 0, tool_results: 0, tool_calls: 0, thinking_blocks: 0, models: [] },
  };
  return btoa(unescape(encodeURIComponent(JSON.stringify(payload))));
}

function installStubs() {
  // 透传 parse,让原始 HTML 完整流经 sanitizeHtml(被测路径)
  (globalThis as unknown as { marked: unknown }).marked = {
    use() {
      /* no-op */
    },
    parse(text: string) {
      return text;
    },
  };
  (globalThis as unknown as { hljs: unknown }).hljs = {
    getLanguage() {
      return null;
    },
    highlight(text: string) {
      return { value: escHtml(text) };
    },
    highlightAuto(text: string) {
      return { value: escHtml(text) };
    },
  };
}

function teardownStubs() {
  delete (globalThis as unknown as { marked?: unknown }).marked;
  delete (globalThis as unknown as { hljs?: unknown }).hljs;
  delete (window as unknown as { __sagePwn?: unknown }).__sagePwn;
  delete (window as unknown as { __sagePwn2?: unknown }).__sagePwn2;
}

function buildDom(b64: string) {
  document.body.innerHTML =
    '<header><h1 id="session-title"></h1>' +
    '<button id="theme-toggle" type="button"></button>' +
    '<div id="session-info"></div></header>' +
    '<main id="messages"></main>';
  const data = document.createElement('script');
  data.id = 'session-data';
  data.setAttribute('type', 'application/json');
  data.textContent = b64;
  document.body.appendChild(data);
}

describe('export template.js — sanitizeHtml security guard (U18)', () => {
  beforeEach(() => {
    teardownStubs();
    installStubs();
  });
  afterEach(() => {
    teardownStubs();
  });

  it('neutralizes meta-refresh, onerror and onload; never executes them', () => {
    buildDom(payloadBase64(HOSTILE));

    // 执行自包含模板 IIFE,以便在真实渲染管线里测试其内部 sanitizeHtml
    const run = new Function(templateJs);
    run();

    const messages = document.getElementById('messages') as HTMLElement;
    const html = messages.innerHTML;

    // 标签被降级为转义文本(正向证据),且 DOM 中无活标签
    expect(html).toContain('&lt;meta');
    expect(messages.querySelector('meta')).toBeNull();
    expect(messages.querySelector('img[onerror]')).toBeNull();
    expect(messages.querySelector('[onload]')).toBeNull();

    // 内联事件处理器从不执行
    expect((window as unknown as { __sagePwn?: unknown }).__sagePwn).toBeUndefined();
    expect((window as unknown as { __sagePwn2?: unknown }).__sagePwn2).toBeUndefined();

    // 正向对照:正常消息确实渲染了(证明 IIFE 完整跑通,而非静默失败)
    expect(messages.querySelector('.user-message')).not.toBeNull();
    expect(html).toContain('正常文本');
  });
});
