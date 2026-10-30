import { describe, expect, it, vi } from 'vitest';

import type { TranslationKey } from '../../../shared/lib/i18n';
import { zh } from '../../../shared/lib/i18n/zh';
import type {
  ContextMenuActionItem,
  ContextMenuItemSpec,
} from '../../../shared/ui/ContextMenu/types';
import { buildSessionContextMenuItems } from '../sessionContextMenu';

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

function build(overrides: Partial<Parameters<typeof buildSessionContextMenuItems>[0]> = {}) {
  return buildSessionContextMenuItems({
    session: { id: 's-1', title: '会话 A', is_pinned: false, fork_root: null },
    t,
    onOpen: vi.fn(),
    onRename: vi.fn(),
    onTogglePin: vi.fn(),
    onCopyTitle: vi.fn(),
    onExportHtml: vi.fn(),
    onExportMarkdown: vi.fn(),
    onViewForkTree: vi.fn(),
    onDelete: vi.fn(),
    ...overrides,
  });
}

describe('buildSessionContextMenuItems', () => {
  it('returns the core session actions in a stable order', () => {
    const items = build();

    expect(ids(items)).toEqual([
      'open',
      'rename',
      'pin',
      'copy-title',
      'sep-actions',
      'export-markdown',
      'export-html',
      'sep-delete',
      'delete',
    ]);
    expect(item(items, 'delete').destructive).toBe(true);
  });

  it('renders the pin item according to the current pin state', () => {
    expect(item(build(), 'pin').label).toBe(zh['contextMenu.session.pin']);
    expect(
      item(
        build({ session: { id: 's-1', title: '会话 A', is_pinned: true, fork_root: null } }),
        'pin',
      ).label,
    ).toBe(zh['contextMenu.session.unpin']);
  });

  it('only exposes the fork-tree item for forked sessions', () => {
    expect(ids(build())).not.toContain('fork-tree');
    expect(
      ids(
        build({
          session: { id: 's-1', title: '会话 A', is_pinned: false, fork_root: 'root-1' },
        }),
      ),
    ).toContain('fork-tree');
  });

  it('adds archive/unarchive entries only when their handlers exist', () => {
    expect(ids(build())).not.toContain('archive');
    expect(ids(build())).not.toContain('unarchive');

    const archiveItems = build({ onArchive: vi.fn(), archiveDisabled: true });
    expect(item(archiveItems, 'archive').disabled).toBe(true);

    const unarchiveItems = build({ onUnarchive: vi.fn() });
    expect(ids(unarchiveItems)).toContain('unarchive');
  });

  it('disables pin/export items while their operations are running', () => {
    const items = build({ pinning: true, exportingHtml: true, exportingMarkdown: true });

    expect(item(items, 'pin').disabled).toBe(true);
    expect(item(items, 'export-html').disabled).toBe(true);
    expect(item(items, 'export-markdown').disabled).toBe(true);
  });

  it('wires each onSelect to the injected handler', () => {
    const handlers = {
      onOpen: vi.fn(),
      onRename: vi.fn(),
      onTogglePin: vi.fn(),
      onCopyTitle: vi.fn(),
      onExportHtml: vi.fn(),
      onExportMarkdown: vi.fn(),
      onViewForkTree: vi.fn(),
      onDelete: vi.fn(),
    };
    const items = build({
      session: { id: 's-1', title: '会话 A', is_pinned: false, fork_root: 'root-1' },
      ...handlers,
    });

    for (const [id, handler] of [
      ['open', handlers.onOpen],
      ['rename', handlers.onRename],
      ['pin', handlers.onTogglePin],
      ['copy-title', handlers.onCopyTitle],
      ['export-html', handlers.onExportHtml],
      ['export-markdown', handlers.onExportMarkdown],
      ['fork-tree', handlers.onViewForkTree],
      ['delete', handlers.onDelete],
    ] as const) {
      const spec = item(items, id);
      spec.onSelect();
      expect(handler).toHaveBeenCalledTimes(1);
    }
  });
});
