import { describe, expect, it, vi } from 'vitest';

import type { TranslationKey } from '../../../shared/lib/i18n';
import { zh } from '../../../shared/lib/i18n/zh';
import type {
  ContextMenuActionItem,
  ContextMenuItemSpec,
} from '../../../shared/ui/ContextMenu/types';
import { buildMessageContextMenuItems } from '../messageContextMenu';

const t = (key: TranslationKey) => (zh as Record<string, string>)[key] ?? key;

function ids(items: ContextMenuItemSpec[]): string[] {
  return items.map((item) => item.id);
}

function item(items: ContextMenuItemSpec[], id: string): ContextMenuActionItem {
  const found = items.find((entry) => entry.id === id);
  if (!found || (found.kind !== undefined && found.kind !== 'item')) {
    throw new Error(`missing item ${id}`);
  }
  return found;
}

type Params = Parameters<typeof buildMessageContextMenuItems>[0];

function build(overrides: Partial<Params> = {}) {
  return buildMessageContextMenuItems({
    message: { id: 'a-1', role: 'assistant', content: '回答内容' },
    t,
    onCopySelection: vi.fn(),
    onQuoteSelection: vi.fn(),
    onCopy: vi.fn(),
    onCopyMarkdown: vi.fn(),
    ...overrides,
  });
}

describe('buildMessageContextMenuItems', () => {
  it('builds the assistant action set with all injected handlers', () => {
    const items = build({
      onQuote: vi.fn(),
      onRegenerate: vi.fn(),
      onFeedback: vi.fn(),
      onFork: vi.fn(),
      onRewind: vi.fn(),
      onSaveToMemory: vi.fn(),
      onDelete: vi.fn(),
    });

    expect(ids(items)).toEqual([
      'copy',
      'copy-markdown',
      'quote',
      'regenerate',
      'feedback-up',
      'feedback-down',
      'fork',
      'rewind',
      'save-to-memory',
      'sep-delete',
      'delete',
    ]);
    expect(item(items, 'delete').destructive).toBe(true);
  });

  it('uses edit-resend for user messages and omits regenerate', () => {
    const items = build({
      message: { id: 'u-1', role: 'user', content: '提问' },
      onEditResend: vi.fn(),
      onRegenerate: vi.fn(),
    });

    expect(ids(items)).toContain('edit-resend');
    expect(ids(items)).not.toContain('regenerate');
  });

  it('prepends selection actions only when a selection exists', () => {
    const base = build();
    expect(ids(base)).not.toContain('copy-selection');

    const withSelection = build({ selectionText: '选中的一段话' });
    expect(ids(withSelection).slice(0, 3)).toEqual([
      'copy-selection',
      'quote-selection',
      'sep-selection',
    ]);
  });

  it('disables generation and destructive actions while streaming but keeps copy', () => {
    const items = build({
      isStreaming: true,
      selectionText: '选中',
      onQuote: vi.fn(),
      onRegenerate: vi.fn(),
      onFork: vi.fn(),
      onDelete: vi.fn(),
    });

    expect(item(items, 'copy').disabled).toBe(false);
    expect(item(items, 'copy-markdown').disabled).toBe(false);
    expect(item(items, 'copy-selection').disabled).toBeFalsy();
    expect(item(items, 'quote-selection').disabled).toBe(true);
    expect(item(items, 'quote').disabled).toBe(true);
    expect(item(items, 'regenerate').disabled).toBe(true);
    expect(item(items, 'fork').disabled).toBe(true);
    expect(item(items, 'delete').disabled).toBe(true);
  });

  it('disables copy items when the message body is empty', () => {
    const items = build({ message: { id: 'a-2', role: 'assistant', content: '   ' } });

    expect(item(items, 'copy').disabled).toBe(true);
    expect(item(items, 'copy-markdown').disabled).toBe(true);
  });

  it('disables quote-selection when no quote handler is available', () => {
    const items = build({ selectionText: '选中', onQuoteSelection: undefined });
    expect(item(items, 'quote-selection').disabled).toBe(true);
  });

  it('gates quote-selection on the selection handler, not the whole-message handler', () => {
    const onlyWhole = build({
      selectionText: '选中',
      onQuote: vi.fn(),
      onQuoteSelection: undefined,
    });
    expect(item(onlyWhole, 'quote-selection').disabled).toBe(true);

    const withSelection = build({ selectionText: '选中', onQuoteSelection: vi.fn() });
    expect(item(withSelection, 'quote-selection').disabled).toBe(false);
  });

  it('wires feedback directions and selection handlers', () => {
    const onFeedback = vi.fn();
    const onCopySelection = vi.fn();
    const onQuoteSelection = vi.fn();
    const items = build({
      selectionText: '选中',
      onFeedback,
      onCopySelection,
      onQuoteSelection,
      onQuote: vi.fn(),
    });

    item(items, 'feedback-up').onSelect();
    item(items, 'feedback-down').onSelect();
    item(items, 'copy-selection').onSelect();
    item(items, 'quote-selection').onSelect();

    expect(onFeedback).toHaveBeenNthCalledWith(1, 'up');
    expect(onFeedback).toHaveBeenNthCalledWith(2, 'down');
    expect(onCopySelection).toHaveBeenCalledTimes(1);
    expect(onQuoteSelection).toHaveBeenCalledTimes(1);
  });
});
