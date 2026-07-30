import { useCallback, useEffect, useRef } from 'react';

/**
 * Emacs-style keyboard bindings for textareas (U20).
 *
 * Bindings (all line-oriented, operating on physical `\n`-separated lines):
 *
 * | Shortcut | Action                                   |
 * | -------- | ---------------------------------------- |
 * | Ctrl+A   | Move cursor to start of line             |
 * | Ctrl+E   | Move cursor to end of line               |
 * | Ctrl+K   | Kill (delete) from cursor to end of line |
 * | Ctrl+U   | Kill from start of line to cursor        |
 * | Ctrl+W   | Kill the word before the cursor          |
 * | Alt+B    | Move backward one word                   |
 * | Alt+F    | Move forward one word                    |
 *
 * Semantics mirror the pi TUI editor (`packages/tui/src/components/editor.ts`),
 * minus the kill ring: Ctrl+K at the end of a line deletes the line break
 * (joining with the next line); Ctrl+U at the start of a line joins with the
 * previous line; Ctrl+W at the start of a line joins with the previous line.
 * With an active selection, Ctrl+K / Ctrl+U / Ctrl+W kill the selected region.
 *
 * Platform notes:
 * - Alt+B / Alt+F are matched on `event.code` so they work on macOS, where
 *   `alt` + letter produces special characters (`∫`, `ƒ`) as `event.key`.
 * - On Windows/Linux, Alt+F may activate the Electron application menu bar at
 *   the OS level when the menu is visible; the binding still works while the
 *   menu bar is hidden.
 * - Meta (Cmd) combinations are intentionally not intercepted, so native
 *   shortcuts such as Cmd+A (select all) keep working on macOS.
 */

export interface UseEmacsKeybindingsOptions {
  /** Current controlled value of the textarea. */
  value: string;
  /** Called with the new value when a destructive binding fires. */
  onChange: (value: string) => void;
  /** Set to false to disable all bindings (e.g. while disabled/loading). */
  enabled?: boolean;
}

export interface UseEmacsKeybindingsResult {
  /** Attach to the target `<textarea>` so cursor restoration works. */
  ref: React.RefObject<HTMLTextAreaElement>;
  /**
   * Attach to the textarea's `onKeyDown`. Returns `true` when an Emacs
   * binding consumed the event (already `preventDefault`-ed); callers should
   * skip their own key handling in that case.
   */
  handleKeyDown: (event: React.KeyboardEvent<HTMLTextAreaElement>) => boolean;
}

// ---------------------------------------------------------------------------
// Pure text helpers (exported for unit testing)
// ---------------------------------------------------------------------------

const WORD_CHAR_RE = /[\p{L}\p{N}_]/u;
const WHITESPACE_RE = /\s/u;

function isWordChar(text: string, index: number): boolean {
  return WORD_CHAR_RE.test(text[index] ?? '');
}

function isWhitespace(text: string, index: number): boolean {
  return WHITESPACE_RE.test(text[index] ?? '');
}

/**
 * Index of the start of the physical line containing `index`.
 * Pure function — does not mutate anything.
 */
export function lineStartOf(text: string, index: number): number {
  const clamped = Math.max(0, Math.min(index, text.length));
  const newline = text.lastIndexOf('\n', clamped - 1);
  return newline === -1 ? 0 : newline + 1;
}

/**
 * Index of the end of the physical line containing `index`
 * (position of the terminating `\n`, or `text.length` for the last line).
 */
export function lineEndOf(text: string, index: number): number {
  const clamped = Math.max(0, Math.min(index, text.length));
  const newline = text.indexOf('\n', clamped);
  return newline === -1 ? text.length : newline;
}

/**
 * Cursor position after moving one word backward from `cursor`.
 * Skips whitespace adjacent to the cursor, then a run of word characters
 * (Unicode letters/digits/underscore) or a run of punctuation.
 * Returns 0 when already at the start.
 */
export function findWordBackward(text: string, cursor: number): number {
  let i = Math.max(0, Math.min(cursor, text.length));
  while (i > 0 && isWhitespace(text, i - 1)) i -= 1;
  if (i === 0) return 0;
  if (isWordChar(text, i - 1)) {
    while (i > 0 && isWordChar(text, i - 1)) i -= 1;
  } else {
    while (i > 0 && !isWordChar(text, i - 1) && !isWhitespace(text, i - 1)) i -= 1;
  }
  return i;
}

/**
 * Cursor position after moving one word forward from `cursor`.
 * Mirrors `findWordBackward`: skips adjacent whitespace, then a word or
 * punctuation run. Returns `text.length` when already at the end.
 */
export function findWordForward(text: string, cursor: number): number {
  const length = text.length;
  let i = Math.max(0, Math.min(cursor, length));
  while (i < length && isWhitespace(text, i)) i += 1;
  if (i >= length) return length;
  if (isWordChar(text, i)) {
    while (i < length && isWordChar(text, i)) i += 1;
  } else {
    while (i < length && !isWordChar(text, i) && !isWhitespace(text, i)) i += 1;
  }
  return i;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useEmacsKeybindings({
  value,
  onChange,
  enabled = true,
}: UseEmacsKeybindingsOptions): UseEmacsKeybindingsResult {
  const ref = useRef<HTMLTextAreaElement>(null);
  // Cursor position to restore after React commits the controlled value
  // update (React's DOM `value` write collapses the selection to the end).
  const pendingCursor = useRef<number | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (el && pendingCursor.current !== null) {
      el.setSelectionRange(pendingCursor.current, pendingCursor.current);
      pendingCursor.current = null;
    }
  }, [value]);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLTextAreaElement>): boolean => {
      if (!enabled) return false;
      const el = event.currentTarget ?? ref.current;
      if (!el) return false;

      const text = el.value;
      const start = el.selectionStart ?? 0;
      const end = el.selectionEnd ?? 0;

      // Movement-only: no value change, so no re-render — applying the
      // selection synchronously is sufficient.
      const moveCursor = (pos: number) => {
        el.setSelectionRange(pos, pos);
      };
      // Destructive: notify the owner and restore the cursor after React
      // re-renders the controlled value (see effect above).
      const killRange = (deleteFrom: number, deleteTo: number) => {
        const next = text.slice(0, deleteFrom) + text.slice(deleteTo);
        if (next === text) return;
        pendingCursor.current = deleteFrom;
        onChange(next);
        el.setSelectionRange(deleteFrom, deleteFrom);
      };

      const ctrlOnly = event.ctrlKey && !event.altKey && !event.metaKey && !event.shiftKey;
      const altOnly = event.altKey && !event.ctrlKey && !event.metaKey && !event.shiftKey;
      const hasSelection = start !== end;

      if (ctrlOnly) {
        switch (event.key.toLowerCase()) {
          case 'a':
            event.preventDefault();
            moveCursor(lineStartOf(text, start));
            return true;
          case 'e':
            event.preventDefault();
            moveCursor(lineEndOf(text, end));
            return true;
          case 'k': {
            event.preventDefault();
            if (hasSelection) {
              killRange(start, end);
            } else {
              const lineEnd = lineEndOf(text, start);
              if (lineEnd > start) {
                killRange(start, lineEnd);
              } else if (lineEnd < text.length) {
                // Cursor at end of line: kill the line break, joining lines.
                killRange(start, lineEnd + 1);
              }
            }
            return true;
          }
          case 'u': {
            event.preventDefault();
            if (hasSelection) {
              killRange(start, end);
            } else {
              const lineStart = lineStartOf(text, start);
              if (lineStart < start) {
                killRange(lineStart, start);
              } else if (lineStart > 0) {
                // Cursor at start of line: kill the preceding line break.
                killRange(lineStart - 1, start);
              }
            }
            return true;
          }
          case 'w': {
            event.preventDefault();
            if (hasSelection) {
              killRange(start, end);
            } else if (start > 0) {
              const lineStart = lineStartOf(text, start);
              if (start === lineStart) {
                // Cursor at start of line: kill the preceding line break
                // (join with previous line), mirroring the pi editor.
                killRange(lineStart - 1, start);
              } else {
                // Never cross the line break: clamp at the line start.
                killRange(Math.max(findWordBackward(text, start), lineStart), start);
              }
            }
            return true;
          }
          default:
            return false;
        }
      }

      if (altOnly) {
        // Match on event.code: on macOS, alt+b/alt+f produce '∫'/'ƒ' keys.
        if (event.code === 'KeyB') {
          event.preventDefault();
          moveCursor(findWordBackward(text, start));
          return true;
        }
        if (event.code === 'KeyF') {
          event.preventDefault();
          moveCursor(findWordForward(text, end));
          return true;
        }
      }

      return false;
    },
    [enabled, onChange],
  );

  return { ref, handleKeyDown };
}
