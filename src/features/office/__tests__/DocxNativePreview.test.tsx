/**
 * DocxNativePreview sanitize 单测（P2-B）—— 渲染树消毒规则：
 * 去 script/iframe/object/embed/link 节点、javascript: 链接、on* 内联事件。
 */

import { describe, expect, it } from 'vitest';

import { sanitizeRenderedDocx } from '../DocxNativePreview';

function makeContainer(html: string): HTMLElement {
  const div = document.createElement('div');
  div.innerHTML = html;
  return div;
}

describe('sanitizeRenderedDocx', () => {
  it('removes script/iframe/object/embed/link nodes', () => {
    const c = makeContainer(
      '<p>safe</p><script>window.x=1</script><iframe src="a"></iframe><object></object><embed><link rel="x">',
    );
    sanitizeRenderedDocx(c);
    expect(c.querySelectorAll('script,iframe,object,embed,link').length).toBe(0);
    expect(c.querySelector('p')?.textContent).toBe('safe');
  });

  it('strips javascript: hrefs and srcs', () => {
    const c = makeContainer(
      '<a href="javascript:alert(1)">x</a><img src="javascript:alert(2)"><a href="https://ok.example">ok</a>',
    );
    sanitizeRenderedDocx(c);
    const links = c.querySelectorAll('a');
    expect(links[0].getAttribute('href')).toBeNull();
    expect(links[1].getAttribute('href')).toBe('https://ok.example');
    expect(c.querySelector('img')?.getAttribute('src')).toBeNull();
  });

  it('strips on* inline event attributes', () => {
    const c = makeContainer('<p onclick="alert(1)" onmouseover="x()">t</p>');
    sanitizeRenderedDocx(c);
    const p = c.querySelector('p')!;
    expect(p.getAttribute('onclick')).toBeNull();
    expect(p.getAttribute('onmouseover')).toBeNull();
    expect(p.textContent).toBe('t');
  });
});
