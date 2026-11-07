import { beforeEach, describe, expect, it } from 'vitest';

import {
  annotateParagraphIndexes,
  collectDocumentParagraphs,
  findParagraphIndex,
  normalizeSelection,
} from '../selectionAnchor';

function buildRoot(html: string): HTMLElement {
  const root = document.createElement('div');
  root.innerHTML = html;
  document.body.appendChild(root);
  return root;
}

describe('selectionAnchor', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('injects 0-based indices skipping empty and table paragraphs', () => {
    const root = buildRoot(
      '<header><p>页眉</p></header><p>first</p><p>   </p><table><tr><td><p>cell</p></td></tr></table><p>second</p><footer><p>页脚</p></footer>',
    );

    annotateParagraphIndexes(root);

    const indexed = Array.from(root.querySelectorAll('[data-paragraph-index]')).map((el) => [
      el.textContent,
      el.getAttribute('data-paragraph-index'),
    ]);
    expect(indexed).toEqual([
      ['first', '0'],
      ['second', '1'],
    ]);
  });

  it('re-annotates idempotently', () => {
    const root = buildRoot('<p>a</p><p>b</p>');
    annotateParagraphIndexes(root);
    annotateParagraphIndexes(root);
    expect(root.querySelectorAll('[data-paragraph-index]')).toHaveLength(2);
  });

  it('finds the nearest paragraph index from a text node', () => {
    const root = buildRoot('<p>a</p><p>hello world</p>');
    annotateParagraphIndexes(root);
    const text = root.querySelectorAll('p')[1].firstChild;

    expect(findParagraphIndex(text, root)).toBe(1);
  });

  it('returns null when the node is outside any paragraph', () => {
    const root = buildRoot('<div>loose</div>');
    expect(findParagraphIndex(root.querySelector('div'), root)).toBeNull();
  });

  it('collects paragraph texts in index order', () => {
    const root = buildRoot('<p>a</p><p>b</p>');
    annotateParagraphIndexes(root);

    expect(collectDocumentParagraphs(root)).toEqual([
      { index: 0, text: 'a' },
      { index: 1, text: 'b' },
    ]);
  });

  it('returns null for a collapsed selection', () => {
    const root = buildRoot('<p>hello</p>');
    annotateParagraphIndexes(root);
    const range = document.createRange();
    range.setStart(root.querySelector('p')!.firstChild!, 2);
    range.collapse(true);
    const selection = window.getSelection()!;
    selection.removeAllRanges();
    selection.addRange(range);

    expect(normalizeSelection(root, selection)).toBeNull();
  });

  it('captures text and both paragraph anchors', () => {
    const root = buildRoot('<p>hello</p><p>world</p>');
    annotateParagraphIndexes(root);
    const range = document.createRange();
    range.setStart(root.querySelectorAll('p')[0].firstChild!, 1);
    range.setEnd(root.querySelectorAll('p')[1].firstChild!, 3);
    const selection = window.getSelection()!;
    selection.removeAllRanges();
    selection.addRange(range);

    const result = normalizeSelection(root, selection);

    expect(result?.text).toBe('ellowor');
    expect(result?.anchorParaIndex).toBe(0);
    expect(result?.focusParaIndex).toBe(1);
    expect(result?.rawContext).toBe('ellowor');
  });
});
