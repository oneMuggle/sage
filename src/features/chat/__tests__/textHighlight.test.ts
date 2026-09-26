// 对话阅读体验 B3 / B4：CSS Custom Highlight API 高亮 —— 正文范围内匹配、跨行内标记、
// 搜索命中自动清除、查找的当前命中、无 API 时静默降级、Range 居中滚动。
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  clearFindHighlights,
  FIND_CURRENT_HIGHLIGHT,
  FIND_HIGHLIGHT,
  findTextRanges,
  highlightFindMatches,
  highlightSearchHits,
  isHighlightSupported,
  scrollRangeIntoView,
  SEARCH_HIT_HIGHLIGHT,
  SEARCH_HIT_HIGHLIGHT_MS,
} from '../textHighlight';

class FakeHighlight {
  ranges: Range[];
  priority = 0;
  constructor(...ranges: Range[]) {
    this.ranges = ranges;
  }
}

function installHighlights(): Map<string, FakeHighlight> {
  const registry = new Map<string, FakeHighlight>();
  vi.stubGlobal('Highlight', FakeHighlight);
  vi.stubGlobal('CSS', { highlights: registry });
  return registry;
}

function mount(html: string): HTMLElement {
  const root = document.createElement('div');
  root.innerHTML = html;
  document.body.appendChild(root);
  return root;
}

afterEach(() => {
  document.body.innerHTML = '';
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('textHighlight (B3 / B4)', () => {
  it('matches case-insensitively inside message bodies only, across inline markup', () => {
    const root = mount(
      '<div data-message-id="m1"><div data-quote-scope="message-body">' +
        '<p>Sage 是 <strong>sa</strong>ge 助手</p>' +
        '<pre><button>Copy sage</button><code>sage()</code></pre>' +
        '<span class="katex-mathml">sage</span>' +
        '</div><div class="sources">sage.dev</div></div>',
    );
    expect(findTextRanges(root, ' SAGE ').map((r) => r.toString())).toEqual([
      'Sage',
      'sage',
      'sage',
    ]);
    expect(findTextRanges(root, '   ')).toEqual([]);
  });

  it('B3: highlights every hit in the target message and clears them later', () => {
    vi.useFakeTimers();
    const registry = installHighlights();
    const root = mount('<div data-quote-scope="message-body"><p>alpha beta gamma alpha</p></div>');
    expect(isHighlightSupported()).toBe(true);
    const first = highlightSearchHits(root, 'alpha');
    expect(first?.toString()).toBe('alpha');
    expect(first?.startOffset).toBe(0);
    expect(registry.get(SEARCH_HIT_HIGHLIGHT)?.ranges).toHaveLength(2);

    vi.advanceTimersByTime(SEARCH_HIT_HIGHLIGHT_MS);
    expect(registry.has(SEARCH_HIT_HIGHLIGHT)).toBe(false);
  });

  it('B3: falls back to per-term hits (document order) when the phrase is not literal', () => {
    vi.useFakeTimers();
    const registry = installHighlights();
    const root = mount('<div data-quote-scope="message-body"><p>gamma then alpha</p></div>');
    expect(highlightSearchHits(root, 'alpha gamma')?.toString()).toBe('gamma');
    expect(registry.get(SEARCH_HIT_HIGHLIGHT)?.ranges.map((r) => r.toString())).toEqual([
      'gamma',
      'alpha',
    ]);
  });

  it('B4: marks every rendered match and emphasises the current one', () => {
    const registry = installHighlights();
    const root = mount(
      '<div data-message-id="a"><div data-quote-scope="message-body">foo x foo</div></div>' +
        '<div data-message-id="b"><div data-quote-scope="message-body">Foo</div></div>',
    );
    const messageA = root.querySelector('[data-message-id="a"]') as Element;
    const current = highlightFindMatches(root, messageA, 'foo', 1);
    expect(current?.startOffset).toBe(6);
    expect(registry.get(FIND_HIGHLIGHT)?.ranges).toHaveLength(3);
    expect(registry.get(FIND_CURRENT_HIGHLIGHT)?.priority).toBe(1);
    expect(registry.get(FIND_CURRENT_HIGHLIGHT)?.ranges).toEqual([current]);

    // 序号越界时取该消息内最后一处
    expect(highlightFindMatches(root, messageA, 'foo', 9)?.startOffset).toBe(6);
    clearFindHighlights();
    expect(registry.size).toBe(0);
  });

  it('degrades silently without the Highlight API and still returns the hit', () => {
    vi.useFakeTimers();
    const root = mount('<div data-quote-scope="message-body">needle</div>');
    expect(isHighlightSupported()).toBe(false);
    expect(highlightSearchHits(root, 'needle')?.toString()).toBe('needle');
    expect(() => clearFindHighlights()).not.toThrow();
  });

  it('scrolls a visible range to the middle of the scroll container', () => {
    const scroller = document.createElement('div');
    let top = 50;
    Object.defineProperty(scroller, 'scrollTop', {
      configurable: true,
      get: () => top,
      set: (value: number) => {
        top = value;
      },
    });
    scroller.getBoundingClientRect = () => ({ top: 100, height: 400 }) as DOMRect;
    const rangeAt = (rect: Partial<DOMRect>) =>
      ({ getBoundingClientRect: () => rect as DOMRect }) as unknown as Range;

    expect(scrollRangeIntoView(rangeAt({ top: 700, height: 20, width: 40 }), scroller)).toBe(true);
    // 50 + (700 - 100 - (400 - 20) / 2)
    expect(top).toBe(460);
    // 不可见（零尺寸）或没有滚动容器时交给调用方回退
    expect(scrollRangeIntoView(rangeAt({ top: 0, height: 0, width: 0 }), scroller)).toBe(false);
    expect(scrollRangeIntoView(rangeAt({ top: 700, height: 20, width: 40 }), null)).toBe(false);
    expect(scrollRangeIntoView(document.createRange(), scroller)).toBe(false);
  });
});
