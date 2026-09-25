// 对话阅读导航 A4/A5: 划词引用与引用追加的纯函数。
import { afterEach, describe, expect, it } from 'vitest';

import {
  appendQuoteToDraft,
  computeQuoteButtonPosition,
  formatQuoteBlock,
  getQuotableSelection,
  normalizeSelectedText,
} from '../selectionQuote';

describe('normalizeSelectedText', () => {
  it('normalizes line endings, trailing blanks and long blank runs', () => {
    expect(normalizeSelectedText('  a  \r\nb\t\n\n\n\nc  ')).toBe('a\nb\n\nc');
  });

  it('returns empty string for whitespace-only selections', () => {
    expect(normalizeSelectedText(' \n\t ')).toBe('');
  });
});

describe('formatQuoteBlock', () => {
  it('prefixes every line and keeps blank lines as bare markers', () => {
    expect(formatQuoteBlock('第一行\n\n第三行')).toBe('> 第一行\n>\n> 第三行');
  });
});

describe('appendQuoteToDraft', () => {
  it('uses the quote alone when the draft is empty', () => {
    expect(appendQuoteToDraft('', '> q')).toBe('> q\n\n');
  });

  it('keeps the typed draft and appends the quote after a blank line', () => {
    expect(appendQuoteToDraft('我的问题  \n', '> q')).toBe('我的问题\n\n> q\n\n');
  });

  it('accumulates consecutive quotes', () => {
    const once = appendQuoteToDraft('', '> a');
    expect(appendQuoteToDraft(once, '> b')).toBe('> a\n\n> b\n\n');
  });

  it('leaves the draft untouched for an empty quote', () => {
    expect(appendQuoteToDraft('draft', '  ')).toBe('draft');
  });
});

describe('getQuotableSelection', () => {
  afterEach(() => {
    window.getSelection()?.removeAllRanges();
    document.body.innerHTML = '';
  });

  function setup() {
    document.body.innerHTML = `
      <div id="root">
        <div data-quote-scope="message-body"><p id="a">第一条消息正文</p></div>
        <div data-quote-scope="message-body"><p id="b">第二条消息正文</p></div>
        <button id="btn">复制</button>
      </div>
      <p id="outside">列表外</p>`;
    return document.getElementById('root') as HTMLElement;
  }

  function select(startId: string, endId: string = startId) {
    const selection = window.getSelection() as Selection;
    const range = document.createRange();
    range.setStart(document.getElementById(startId)!.firstChild!, 0);
    const end = document.getElementById(endId)!.firstChild!;
    range.setEnd(end, end.textContent!.length);
    selection.removeAllRanges();
    selection.addRange(range);
    return selection;
  }

  it('returns the normalized text for a selection inside one message body', () => {
    const root = setup();
    const info = getQuotableSelection(select('a'), root);
    expect(info?.text).toBe('第一条消息正文');
  });

  it('rejects selections spanning two messages', () => {
    const root = setup();
    expect(getQuotableSelection(select('a', 'b'), root)).toBeNull();
  });

  it('rejects selections outside quote scopes or outside the root', () => {
    const root = setup();
    expect(getQuotableSelection(select('btn'), root)).toBeNull();
    expect(getQuotableSelection(select('outside'), root)).toBeNull();
  });

  it('rejects collapsed selections and missing roots', () => {
    const root = setup();
    const selection = select('a');
    expect(getQuotableSelection(selection, null)).toBeNull();
    selection.collapseToStart();
    expect(getQuotableSelection(selection, root)).toBeNull();
  });
});

describe('computeQuoteButtonPosition', () => {
  it('falls back to the viewport corner without a rect', () => {
    expect(computeQuoteButtonPosition(null, 1000)).toEqual({ top: 8, left: 8 });
  });

  it('places the button above the selection, centered', () => {
    expect(
      computeQuoteButtonPosition({ top: 200, bottom: 220, left: 100, width: 200 }, 1000),
    ).toEqual({ top: 162, left: 200 });
  });

  it('flips below when there is no room above and clamps to the viewport', () => {
    expect(computeQuoteButtonPosition({ top: 10, bottom: 30, left: 980, width: 40 }, 1000)).toEqual(
      { top: 38, left: 952 },
    );
  });
});
