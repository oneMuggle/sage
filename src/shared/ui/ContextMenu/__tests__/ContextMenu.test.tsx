import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ContextMenu } from '../ContextMenu';
import {
  CONTEXT_MENU_OPEN_EVENT,
  isContextMenuOpen,
  resetContextMenuOpenCount,
} from '../contextMenuEvents';
import type { ContextMenuItemSpec } from '../types';

function renderMenu(
  items: ContextMenuItemSpec[] | (() => ContextMenuItemSpec[]),
  options: { enabled?: boolean } = {},
) {
  return render(
    <ContextMenu items={items} enabled={options.enabled}>
      <div data-testid="target">target</div>
    </ContextMenu>,
  );
}

function openMenu(testId = 'target') {
  fireEvent.contextMenu(screen.getByTestId(testId), { clientX: 40, clientY: 60 });
}

function baseItems(overrides: Partial<ContextMenuItemSpec> = {}) {
  return [{ id: 'copy', label: '复制', onSelect: vi.fn(), ...overrides }] as ContextMenuItemSpec[];
}

describe('ContextMenu', () => {
  it('does not render a menu before right click', () => {
    renderMenu(baseItems());
    expect(screen.queryByRole('menu')).toBeNull();
  });

  it('opens on contextmenu and renders declarative items', async () => {
    renderMenu([
      { id: 'label', kind: 'label', label: '会话' },
      { id: 'copy', label: '复制', onSelect: vi.fn() },
      { id: 'sep', kind: 'separator' },
      { id: 'delete', label: '删除', destructive: true, onSelect: vi.fn() },
    ]);

    openMenu();

    const menu = await screen.findByRole('menu');
    expect(menu).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: '复制' })).toBeInTheDocument();
    const deleteItem = screen.getByRole('menuitem', { name: '删除' });
    expect(deleteItem.className).toContain('text-error');
  });

  it('invokes onSelect and closes the menu', async () => {
    const onSelect = vi.fn();
    renderMenu([{ id: 'copy', label: '复制', onSelect }]);

    openMenu();
    fireEvent.click(await screen.findByRole('menuitem', { name: '复制' }));

    expect(onSelect).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByRole('menu')).toBeNull());
  });

  it('does not invoke onSelect for disabled items', async () => {
    const onSelect = vi.fn();
    renderMenu([{ id: 'copy', label: '复制', disabled: true, onSelect }]);

    openMenu();
    fireEvent.click(await screen.findByRole('menuitem', { name: '复制' }));

    expect(onSelect).not.toHaveBeenCalled();
  });

  it('renders checkbox items with aria-checked and toggles through callback', async () => {
    const onCheckedChange = vi.fn();
    renderMenu([{ id: 'pin', kind: 'checkbox', label: '置顶', checked: true, onCheckedChange }]);

    openMenu();
    const item = await screen.findByRole('menuitemcheckbox', { name: '置顶' });
    expect(item).toHaveAttribute('aria-checked', 'true');

    fireEvent.click(item);
    expect(onCheckedChange).toHaveBeenCalledWith(false);
  });

  it('hides hidden items', async () => {
    renderMenu([
      { id: 'copy', label: '复制', onSelect: vi.fn() },
      { id: 'hidden', label: '隐藏项', hidden: true, onSelect: vi.fn() },
    ]);

    openMenu();
    await screen.findByRole('menu');

    expect(screen.getByRole('menuitem', { name: '复制' })).toBeInTheDocument();
    expect(screen.queryByRole('menuitem', { name: '隐藏项' })).toBeNull();
  });

  it('evaluates item factories only when the menu opens', async () => {
    const factory = vi.fn(() => baseItems());
    renderMenu(factory);

    expect(factory).not.toHaveBeenCalled();

    openMenu();
    await screen.findByRole('menu');
    expect(factory).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('menu')).toBeNull());

    openMenu();
    await screen.findByRole('menu');
    expect(factory).toHaveBeenCalledTimes(2);
  });

  it('closes on Escape', async () => {
    renderMenu(baseItems());

    openMenu();
    const menu = await screen.findByRole('menu');
    fireEvent.keyDown(menu, { key: 'Escape' });

    await waitFor(() => expect(screen.queryByRole('menu')).toBeNull());
  });

  it('renders children without a menu when disabled', () => {
    renderMenu(baseItems(), { enabled: false });

    openMenu();
    expect(screen.queryByRole('menu')).toBeNull();
    expect(screen.getByTestId('target')).toBeInTheDocument();
  });

  it('tracks global open state and notifies listeners once', async () => {
    const listener = vi.fn();
    window.addEventListener(CONTEXT_MENU_OPEN_EVENT, listener);
    resetContextMenuOpenCount();
    renderMenu(baseItems());

    openMenu();
    await screen.findByRole('menu');

    expect(isContextMenuOpen()).toBe(true);
    expect(listener).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('menu')).toBeNull());
    expect(isContextMenuOpen()).toBe(false);

    window.removeEventListener(CONTEXT_MENU_OPEN_EVENT, listener);
  });

  it('releases the global open state when unmounted while open', async () => {
    resetContextMenuOpenCount();
    const { unmount } = renderMenu(baseItems());

    openMenu();
    await screen.findByRole('menu');
    expect(isContextMenuOpen()).toBe(true);

    unmount();
    expect(isContextMenuOpen()).toBe(false);
  });

  it('stops propagation so nested message-level triggers stay closed', async () => {
    const outerOnOpenChange = vi.fn();
    render(
      <ContextMenu
        items={[{ id: 'outer', label: '外层', onSelect: vi.fn() }]}
        onOpenChange={outerOnOpenChange}
      >
        <div data-testid="outer">
          <ContextMenu items={[{ id: 'inner', label: '内层', onSelect: vi.fn() }]}>
            <span data-testid="inner">inner</span>
          </ContextMenu>
        </div>
      </ContextMenu>,
    );

    fireEvent.contextMenu(screen.getByTestId('inner'), { clientX: 5, clientY: 5 });

    expect(await screen.findByRole('menuitem', { name: '内层' })).toBeInTheDocument();
    expect(screen.queryByRole('menuitem', { name: '外层' })).toBeNull();
    expect(outerOnOpenChange).not.toHaveBeenCalledWith(true);
  });
});
