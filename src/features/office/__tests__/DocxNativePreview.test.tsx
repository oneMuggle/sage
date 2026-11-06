/**
 * DocxNativePreview sanitize 单测（P2-B）—— 渲染树消毒规则：
 * 去 script/iframe/object/embed/link 节点、javascript: 链接、on* 内联事件。
 */

import { act, render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { officeApi } from '../../../shared/api/officeApi';
import { I18nProvider } from '../../../shared/lib/i18n';
import {
  DocxNativePreview,
  formatDocxPreviewMetaJson,
  formatDocxPreviewMetaMarkdown,
  sanitizeRenderedDocx,
} from '../DocxNativePreview';

afterEach(() => {
  vi.restoreAllMocks();
});

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

  it('formats docx native preview state as Markdown and JSON', () => {
    const md = formatDocxPreviewMetaMarkdown({
      workspacePath: '/ws/proj',
      managedPath: 'report.docx',
      revision: 'rev1',
      state: 'ok',
    });
    expect(md).toContain('# Word 原生预览状态 (Docx Native Preview)');
    expect(md).toContain('report.docx');
    expect(
      formatDocxPreviewMetaMarkdown({
        workspacePath: '/ws/proj',
        managedPath: 'bad.docx',
        revision: null,
        state: 'error',
      }),
    ).toContain('error');

    const parsed = JSON.parse(
      formatDocxPreviewMetaJson({
        workspacePath: '/ws/proj',
        managedPath: 'report.docx',
        revision: 'rev1',
        state: 'ok',
      }),
    );
    expect(parsed.managedPath).toBe('report.docx');
    expect(parsed.revision).toBe('rev1');
  });
});

describe('DocxNativePreview — onError lifecycle', () => {
  it('does not call onError when the load resolves after unmount', async () => {
    let resolveRead: (value: unknown) => void = () => {};
    vi.spyOn(officeApi, 'readWordData').mockReturnValue(
      new Promise((resolve) => {
        resolveRead = resolve;
      }) as unknown as ReturnType<typeof officeApi.readWordData>,
    );
    const onError = vi.fn();

    const { unmount } = render(
      <I18nProvider defaultLocale="zh">
        <DocxNativePreview
          workspacePath="/tmp/ws"
          managedPath="/tmp/ws/office/word/doc-word/report.docx"
          onError={onError}
        />
      </I18nProvider>,
    );

    // Unmount before the read settles: the in-flight request is now cancelled.
    unmount();
    await act(async () => {
      resolveRead({ ok: false, data_url: null, error: 'boom' });
    });

    expect(onError).not.toHaveBeenCalled();
  });
});
