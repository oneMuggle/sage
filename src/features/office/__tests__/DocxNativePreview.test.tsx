/**
 * DocxNativePreview sanitize 单测（P2-B）—— 渲染树消毒规则：
 * 去 script/iframe/object/embed/link 节点、javascript: 链接、on* 内联事件。
 */

import { act, render, waitFor } from '@testing-library/react';
import { renderAsync } from 'docx-preview';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { officeApi } from '../../../shared/api/officeApi';
import { I18nProvider } from '../../../shared/lib/i18n';
import {
  DocxNativePreview,
  formatDocxPreviewMetaJson,
  formatDocxPreviewMetaMarkdown,
  renderDocxDataUrl,
  sanitizeRenderedDocx,
} from '../DocxNativePreview';

// docx-preview 自身需要真实 OOXML 数据；这里只验证渲染入口的数据流，
// 用假实现替换解析（真实渲染由打包 e2e / 手工验证覆盖）。
vi.mock('docx-preview', () => ({
  renderAsync: vi.fn(async (_blob: Blob, container: HTMLElement) => {
    const p = document.createElement('p');
    p.textContent = 'rendered';
    container.appendChild(p);
  }),
}));

afterEach(() => {
  vi.unstubAllGlobals();
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

describe('renderDocxDataUrl — production CSP compatibility', () => {
  it('decodes data: URLs locally without fetch (packaged CSP blocks fetch(data:))', async () => {
    const fetchSpy = vi.fn(() => Promise.reject(new Error('refused by CSP')));
    vi.stubGlobal('fetch', fetchSpy);
    const container = document.createElement('div');

    await renderDocxDataUrl(
      container,
      'data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,aGVsbG8=',
    );

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(container.textContent).toContain('rendered');
    const [blob] = vi.mocked(renderAsync).mock.calls.at(-1)!;
    expect(blob).toBeInstanceOf(Blob);
    expect((blob as Blob).type).toBe(
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    );
  });
});

describe('DocxNativePreview — error detail', () => {
  it('passes the failure detail to onError instead of swallowing it', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.spyOn(officeApi, 'readWordData').mockResolvedValue({
      ok: true,
      data_url: 'not-a-data-url',
    } as unknown as Awaited<ReturnType<typeof officeApi.readWordData>>);
    const onError = vi.fn();

    render(
      <I18nProvider defaultLocale="zh">
        <DocxNativePreview
          workspacePath="/tmp/ws"
          managedPath="/tmp/ws/office/word/doc-word/report.docx"
          onError={onError}
        />
      </I18nProvider>,
    );

    await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
    expect(onError.mock.calls[0][0]).toContain('invalid data URL');
  });
});
