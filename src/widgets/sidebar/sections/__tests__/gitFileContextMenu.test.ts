import { describe, expect, it, vi } from 'vitest';

import type { TranslationKey } from '../../../../shared/lib/i18n';
import { zh } from '../../../../shared/lib/i18n/zh';
import type { ContextMenuItemSpec } from '../../../../shared/ui/ContextMenu/types';
import { buildGitFileContextMenuItems } from '../gitFileContextMenu';

const t = (key: TranslationKey) => (zh as Record<string, string>)[key] ?? key;

function item(items: ContextMenuItemSpec[], id: string) {
  const found = items.find((entry) => entry.id === id);
  if (!found || (found.kind !== undefined && found.kind !== 'item')) {
    throw new Error(`missing item ${id}`);
  }
  return found;
}

describe('buildGitFileContextMenuItems', () => {
  it('wires diff and copy actions', () => {
    const onViewDiff = vi.fn();
    const onCopyPath = vi.fn();
    const onCopyName = vi.fn();
    const items = buildGitFileContextMenuItems({
      file: { path: 'src/app.ts', status: 'modified' },
      t,
      onViewDiff,
      onCopyPath,
      onCopyName,
    });

    expect(items.map((entry) => entry.id)).toEqual([
      'git-view-diff',
      'git-copy-path',
      'git-copy-name',
    ]);
    item(items, 'git-view-diff').onSelect?.();
    item(items, 'git-copy-path').onSelect?.();
    item(items, 'git-copy-name').onSelect?.();
    expect(onViewDiff).toHaveBeenCalledTimes(1);
    expect(onCopyPath).toHaveBeenCalledTimes(1);
    expect(onCopyName).toHaveBeenCalledTimes(1);
  });
});
