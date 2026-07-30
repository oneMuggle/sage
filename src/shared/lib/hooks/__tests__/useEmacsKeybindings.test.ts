import { act, fireEvent, render, renderHook, screen } from '@testing-library/react';
import { createElement, useState } from 'react';
import type { ChangeEvent as ReactChangeEvent, KeyboardEvent as ReactKeyboardEvent } from 'react';
import { describe, expect, it, vi } from 'vitest';

import {
  findWordBackward,
  findWordForward,
  lineEndOf,
  lineStartOf,
  useEmacsKeybindings,
} from '../useEmacsKeybindings';

// ---------------------------------------------------------------------------
// Pure text helpers
// ---------------------------------------------------------------------------

describe('lineStartOf / lineEndOf', () => {
  it('treats a single-line buffer as one line', () => {
    expect(lineStartOf('hello world', 5)).toBe(0);
    expect(lineEndOf('hello world', 5)).toBe('hello world'.length);
  });

  it('finds physical line boundaries in multi-line text', () => {
    const text = 'hello\nworld\nthird';
    // Second line spans [6, 11)
    expect(lineStartOf(text, 8)).toBe(6);
    expect(lineEndOf(text, 8)).toBe(11);
    // Third line spans [12, end)
    expect(lineStartOf(text, 14)).toBe(12);
    expect(lineEndOf(text, 14)).toBe(text.length);
  });

  it('handles boundary indices (line start, line end, buffer edges)', () => {
    const text = 'ab\ncd';
    expect(lineStartOf(text, 0)).toBe(0);
    expect(lineStartOf(text, 3)).toBe(3); // cursor right after '\n'
    expect(lineEndOf(text, 2)).toBe(2); // cursor right before '\n'
    expect(lineStartOf(text, text.length)).toBe(3);
    expect(lineEndOf(text, text.length)).toBe(text.length);
  });

  it('clamps out-of-range indices', () => {
    expect(lineStartOf('abc', 99)).toBe(0);
    expect(lineEndOf('abc', -5)).toBe(3);
  });
});

describe('findWordBackward', () => {
  it('moves to the start of the previous word', () => {
    expect(findWordBackward('hello world', 11)).toBe(6);
    expect(findWordBackward('hello world', 6)).toBe(0);
  });

  it('returns 0 at or before the buffer start', () => {
    expect(findWordBackward('hello', 0)).toBe(0);
    expect(findWordBackward('', 0)).toBe(0);
  });

  it('skips whitespace adjacent to the cursor', () => {
    expect(findWordBackward('hello world  ', 13)).toBe(6);
  });

  it('treats punctuation runs as a single unit', () => {
    expect(findWordBackward('foo, bar', 8)).toBe(5); // 'bar'
    expect(findWordBackward('foo, bar', 5)).toBe(3); // ', ' run
    expect(findWordBackward('foo, bar', 3)).toBe(0); // 'foo'
  });

  it('handles CJK characters as word characters', () => {
    expect(findWordBackward('你好 世界', 5)).toBe(3);
    expect(findWordBackward('你好 世界', 3)).toBe(0);
  });

  it('keeps digits and underscores inside a word', () => {
    expect(findWordBackward('var_1 = 2', 5)).toBe(0);
    expect(findWordBackward('var_1 = 2', 9)).toBe(8);
  });
});

describe('findWordForward', () => {
  it('moves to the end of the next word', () => {
    expect(findWordForward('hello world', 0)).toBe(5);
    expect(findWordForward('hello world', 5)).toBe(11);
  });

  it('returns length at or beyond the buffer end', () => {
    expect(findWordForward('hello', 5)).toBe(5);
    expect(findWordForward('hello', 99)).toBe(5);
  });

  it('skips whitespace adjacent to the cursor', () => {
    expect(findWordForward('  hello', 0)).toBe(7);
  });

  it('treats punctuation runs as a single unit', () => {
    expect(findWordForward('foo,,, bar', 3)).toBe(6);
    expect(findWordForward('foo,,, bar', 6)).toBe(10);
  });

  it('handles CJK characters as word characters', () => {
    expect(findWordForward('你好 世界', 0)).toBe(2);
    expect(findWordForward('你好 世界', 2)).toBe(5);
  });
});

// ---------------------------------------------------------------------------
// Hook — unit level (handler logic against a bare textarea element)
// ---------------------------------------------------------------------------

interface FakeKeyInit {
  key: string;
  code?: string;
  ctrlKey?: boolean;
  altKey?: boolean;
  metaKey?: boolean;
  shiftKey?: boolean;
}

function makeKeyEvent(
  el: HTMLTextAreaElement,
  init: FakeKeyInit,
): { event: ReactKeyboardEvent<HTMLTextAreaElement>; preventDefault: ReturnType<typeof vi.fn> } {
  const preventDefault = vi.fn();
  const event = {
    key: init.key,
    code: init.code ?? `Key${init.key.toUpperCase()}`,
    ctrlKey: init.ctrlKey ?? false,
    altKey: init.altKey ?? false,
    metaKey: init.metaKey ?? false,
    shiftKey: init.shiftKey ?? false,
    preventDefault,
    currentTarget: el,
  } as unknown as ReactKeyboardEvent<HTMLTextAreaElement>;
  return { event, preventDefault };
}

function makeTextarea(value: string, cursor: number, selectionEnd?: number): HTMLTextAreaElement {
  const el = document.createElement('textarea');
  el.value = value;
  el.setSelectionRange(cursor, selectionEnd ?? cursor);
  return el;
}

function renderBindings(value: string) {
  const onChange = vi.fn();
  const { result } = renderHook(() => useEmacsKeybindings({ value, onChange }));
  return { result, onChange };
}

describe('useEmacsKeybindings — movement bindings', () => {
  it('Ctrl+A moves to line start without changing the value', () => {
    const el = makeTextarea('hello world', 5);
    const { result, onChange } = renderBindings(el.value);
    const { event, preventDefault } = makeKeyEvent(el, { key: 'a', ctrlKey: true });

    expect(result.current.handleKeyDown(event)).toBe(true);
    expect(preventDefault).toHaveBeenCalledOnce();
    expect(el.selectionStart).toBe(0);
    expect(el.selectionEnd).toBe(0);
    expect(onChange).not.toHaveBeenCalled();
  });

  it('Ctrl+A targets the current physical line in multi-line text', () => {
    const el = makeTextarea('hello\nworld', 8);
    const { result } = renderBindings(el.value);
    const { event } = makeKeyEvent(el, { key: 'a', ctrlKey: true });

    result.current.handleKeyDown(event);
    expect(el.selectionStart).toBe(6);
  });

  it('Ctrl+E moves to line end', () => {
    const el = makeTextarea('hello world', 2);
    const { result } = renderBindings(el.value);
    const { event } = makeKeyEvent(el, { key: 'e', ctrlKey: true });

    result.current.handleKeyDown(event);
    expect(el.selectionStart).toBe('hello world'.length);
  });

  it('Ctrl+E stops at the current line break in multi-line text', () => {
    const el = makeTextarea('hello\nworld', 2);
    const { result } = renderBindings(el.value);
    const { event } = makeKeyEvent(el, { key: 'e', ctrlKey: true });

    result.current.handleKeyDown(event);
    expect(el.selectionStart).toBe(5);
  });

  it('Alt+B moves backward one word (matched on event.code for macOS)', () => {
    const el = makeTextarea('hello world', 11);
    const { result } = renderBindings(el.value);
    // macOS produces '∫' as event.key for alt+b — code is what matters.
    const { event } = makeKeyEvent(el, { key: '∫', code: 'KeyB', altKey: true });

    expect(result.current.handleKeyDown(event)).toBe(true);
    expect(el.selectionStart).toBe(6);
  });

  it('Alt+F moves forward one word', () => {
    const el = makeTextarea('hello world', 0);
    const { result } = renderBindings(el.value);
    const { event } = makeKeyEvent(el, { key: 'ƒ', code: 'KeyF', altKey: true });

    expect(result.current.handleKeyDown(event)).toBe(true);
    expect(el.selectionStart).toBe(5);
  });

  it('Ctrl+A is case-insensitive (caps lock)', () => {
    const el = makeTextarea('hello', 3);
    const { result } = renderBindings(el.value);
    const { event } = makeKeyEvent(el, { key: 'A', ctrlKey: true });

    expect(result.current.handleKeyDown(event)).toBe(true);
    expect(el.selectionStart).toBe(0);
  });
});

describe('useEmacsKeybindings — kill bindings', () => {
  it('Ctrl+K deletes from cursor to end of line', () => {
    const el = makeTextarea('hello world', 5);
    const { result, onChange } = renderBindings(el.value);
    const { event, preventDefault } = makeKeyEvent(el, { key: 'k', ctrlKey: true });

    expect(result.current.handleKeyDown(event)).toBe(true);
    expect(preventDefault).toHaveBeenCalledOnce();
    expect(onChange).toHaveBeenCalledWith('hello');
  });

  it('Ctrl+K only kills the current line in multi-line text', () => {
    const el = makeTextarea('hello world\nsecond', 5);
    const { result, onChange } = renderBindings(el.value);
    const { event } = makeKeyEvent(el, { key: 'k', ctrlKey: true });

    result.current.handleKeyDown(event);
    expect(onChange).toHaveBeenCalledWith('hello\nsecond');
  });

  it('Ctrl+K at end of line kills the line break (joins lines)', () => {
    const el = makeTextarea('hello\nworld', 5);
    const { result, onChange } = renderBindings(el.value);
    const { event } = makeKeyEvent(el, { key: 'k', ctrlKey: true });

    result.current.handleKeyDown(event);
    expect(onChange).toHaveBeenCalledWith('helloworld');
  });

  it('Ctrl+K at the very end of the buffer is a no-op', () => {
    const el = makeTextarea('hello', 5);
    const { result, onChange } = renderBindings(el.value);
    const { event } = makeKeyEvent(el, { key: 'k', ctrlKey: true });

    expect(result.current.handleKeyDown(event)).toBe(true);
    expect(onChange).not.toHaveBeenCalled();
  });

  it('Ctrl+K with an active selection kills the region', () => {
    const el = makeTextarea('hello world', 2, 7);
    const { result, onChange } = renderBindings(el.value);
    const { event } = makeKeyEvent(el, { key: 'k', ctrlKey: true });

    result.current.handleKeyDown(event);
    expect(onChange).toHaveBeenCalledWith('heorld');
  });

  it('Ctrl+U deletes from start of line to cursor', () => {
    const el = makeTextarea('hello world', 5);
    const { result, onChange } = renderBindings(el.value);
    const { event } = makeKeyEvent(el, { key: 'u', ctrlKey: true });

    expect(result.current.handleKeyDown(event)).toBe(true);
    expect(onChange).toHaveBeenCalledWith(' world');
  });

  it('Ctrl+U at start of line kills the preceding line break', () => {
    const el = makeTextarea('hello\nworld', 6);
    const { result, onChange } = renderBindings(el.value);
    const { event } = makeKeyEvent(el, { key: 'u', ctrlKey: true });

    result.current.handleKeyDown(event);
    expect(onChange).toHaveBeenCalledWith('helloworld');
  });

  it('Ctrl+U at the very start of the buffer is a no-op', () => {
    const el = makeTextarea('hello', 0);
    const { result, onChange } = renderBindings(el.value);
    const { event } = makeKeyEvent(el, { key: 'u', ctrlKey: true });

    expect(result.current.handleKeyDown(event)).toBe(true);
    expect(onChange).not.toHaveBeenCalled();
  });

  it('Ctrl+W kills the previous word', () => {
    const el = makeTextarea('foo bar baz', 7);
    const { result, onChange } = renderBindings(el.value);
    const { event } = makeKeyEvent(el, { key: 'w', ctrlKey: true });

    result.current.handleKeyDown(event);
    expect(onChange).toHaveBeenCalledWith('foo  baz');
  });

  it('Ctrl+W at start of line joins with the previous line', () => {
    const el = makeTextarea('hello\nworld', 6);
    const { result, onChange } = renderBindings(el.value);
    const { event } = makeKeyEvent(el, { key: 'w', ctrlKey: true });

    result.current.handleKeyDown(event);
    expect(onChange).toHaveBeenCalledWith('helloworld');
  });

  it('Ctrl+W does not cross the line break mid-line', () => {
    // Only whitespace before the cursor on the current line: kill up to the
    // line start, never the preceding line's content.
    const el = makeTextarea('hello\n   world', 9);
    const { result, onChange } = renderBindings(el.value);
    const { event } = makeKeyEvent(el, { key: 'w', ctrlKey: true });

    result.current.handleKeyDown(event);
    expect(onChange).toHaveBeenCalledWith('hello\nworld');
  });

  it('Ctrl+W at buffer start is a no-op', () => {
    const el = makeTextarea('hello', 0);
    const { result, onChange } = renderBindings(el.value);
    const { event } = makeKeyEvent(el, { key: 'w', ctrlKey: true });

    expect(result.current.handleKeyDown(event)).toBe(true);
    expect(onChange).not.toHaveBeenCalled();
  });

  it('Ctrl+W with an active selection kills the region', () => {
    const el = makeTextarea('foo bar baz', 4, 7);
    const { result, onChange } = renderBindings(el.value);
    const { event } = makeKeyEvent(el, { key: 'w', ctrlKey: true });

    result.current.handleKeyDown(event);
    // Deletes 'bar' (indices 4..7), surrounding spaces preserved.
    expect(onChange).toHaveBeenCalledWith('foo  baz');
  });
});

describe('useEmacsKeybindings — non-binding keys pass through', () => {
  it('returns false for plain letters (no modifier)', () => {
    const el = makeTextarea('hello', 2);
    const { result, onChange } = renderBindings(el.value);
    const { event, preventDefault } = makeKeyEvent(el, { key: 'a' });

    expect(result.current.handleKeyDown(event)).toBe(false);
    expect(preventDefault).not.toHaveBeenCalled();
    expect(onChange).not.toHaveBeenCalled();
    expect(el.selectionStart).toBe(2);
  });

  it('does not intercept Meta combinations (native Cmd+A preserved)', () => {
    const el = makeTextarea('hello', 3);
    const { result } = renderBindings(el.value);
    const { event, preventDefault } = makeKeyEvent(el, { key: 'a', metaKey: true });

    expect(result.current.handleKeyDown(event)).toBe(false);
    expect(preventDefault).not.toHaveBeenCalled();
    expect(el.selectionStart).toBe(3);
  });

  it('does not intercept Ctrl+Shift combinations', () => {
    const el = makeTextarea('hello', 3);
    const { result } = renderBindings(el.value);
    const { event } = makeKeyEvent(el, { key: 'a', ctrlKey: true, shiftKey: true });

    expect(result.current.handleKeyDown(event)).toBe(false);
  });

  it('ignores unbound Ctrl letters (e.g. Ctrl+Z undo stays native)', () => {
    const el = makeTextarea('hello', 3);
    const { result } = renderBindings(el.value);
    const { event, preventDefault } = makeKeyEvent(el, { key: 'z', ctrlKey: true });

    expect(result.current.handleKeyDown(event)).toBe(false);
    expect(preventDefault).not.toHaveBeenCalled();
  });

  it('ignores unbound Alt letters (e.g. Alt+G)', () => {
    const el = makeTextarea('hello', 3);
    const { result } = renderBindings(el.value);
    const { event } = makeKeyEvent(el, { key: 'g', code: 'KeyG', altKey: true });

    expect(result.current.handleKeyDown(event)).toBe(false);
  });

  it('is fully inert when enabled=false', () => {
    const el = makeTextarea('hello world', 5);
    const onChange = vi.fn();
    const { result } = renderHook(() =>
      useEmacsKeybindings({ value: el.value, onChange, enabled: false }),
    );
    const { event, preventDefault } = makeKeyEvent(el, { key: 'k', ctrlKey: true });

    expect(result.current.handleKeyDown(event)).toBe(false);
    expect(preventDefault).not.toHaveBeenCalled();
    expect(onChange).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Hook — integration (controlled textarea, cursor restoration after commit)
// ---------------------------------------------------------------------------

function ControlledTextarea({ initial }: { initial: string }) {
  const [value, setValue] = useState(initial);
  const { ref, handleKeyDown } = useEmacsKeybindings({ value, onChange: setValue });
  return createElement('textarea', {
    ref,
    'data-testid': 'emacs-ta',
    value,
    onChange: (e: ReactChangeEvent<HTMLTextAreaElement>) => setValue(e.target.value),
    onKeyDown: (e: ReactKeyboardEvent<HTMLTextAreaElement>) => {
      handleKeyDown(e);
    },
  });
}

function renderControlled(initial: string): HTMLTextAreaElement {
  render(createElement(ControlledTextarea, { initial }));
  return screen.getByTestId('emacs-ta') as HTMLTextAreaElement;
}

describe('useEmacsKeybindings — controlled component integration', () => {
  it('Ctrl+U updates the value and restores the cursor after commit', () => {
    const ta = renderControlled('hello world');
    ta.setSelectionRange(5, 5);

    // Returns false only when default was NOT prevented — Ctrl+U prevents it.
    expect(fireEvent.keyDown(ta, { key: 'u', ctrlKey: true })).toBe(false);

    expect(ta.value).toBe(' world');
    // Without restoration, React's value commit would leave the cursor at
    // the end (6); the hook must restore it to the kill point (0).
    expect(ta.selectionStart).toBe(0);
    expect(ta.selectionEnd).toBe(0);
  });

  it('Ctrl+W restores the cursor mid-buffer after commit', () => {
    const ta = renderControlled('foo bar baz');
    ta.setSelectionRange(7, 7);

    fireEvent.keyDown(ta, { key: 'w', ctrlKey: true });

    expect(ta.value).toBe('foo  baz');
    expect(ta.selectionStart).toBe(4);
    expect(ta.selectionEnd).toBe(4);
  });

  it('movement + kill bindings compose across events', () => {
    const ta = renderControlled('hello\nworld');
    ta.setSelectionRange(8, 8);

    fireEvent.keyDown(ta, { key: 'a', ctrlKey: true }); // → line start (6)
    expect(ta.selectionStart).toBe(6);
    fireEvent.keyDown(ta, { key: 'e', ctrlKey: true }); // → line end (11)
    expect(ta.selectionStart).toBe(11);
    fireEvent.keyDown(ta, { key: 'a', ctrlKey: true }); // → line start (6)
    fireEvent.keyDown(ta, { key: 'k', ctrlKey: true }); // kill 'world'

    expect(ta.value).toBe('hello\n');
    expect(ta.selectionStart).toBe(6);
  });

  it('Alt+F then Ctrl+W deletes the word the cursor moved to the end of', () => {
    const ta = renderControlled('foo bar baz');
    ta.setSelectionRange(0, 0);

    act(() => {
      fireEvent.keyDown(ta, { key: 'f', code: 'KeyF', altKey: true }); // → 3 (end of 'foo')
    });
    expect(ta.selectionStart).toBe(3);
    fireEvent.keyDown(ta, { key: 'w', ctrlKey: true }); // kill 'foo'

    expect(ta.value).toBe(' bar baz');
    expect(ta.selectionStart).toBe(0);
  });

  it('plain typing still flows through the native change handler', () => {
    const ta = renderControlled('hi');
    ta.setSelectionRange(2, 2);

    fireEvent.change(ta, { target: { value: 'hi!' } });
    expect(ta.value).toBe('hi!');
  });
});
