import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '../DropdownMenu';

function renderMenu(onOpenChange = (_open: boolean) => {}) {
  return render(
    <DropdownMenu onOpenChange={onOpenChange}>
      <DropdownMenuTrigger>Actions</DropdownMenuTrigger>
      <DropdownMenuContent>
        <DropdownMenuLabel>Session</DropdownMenuLabel>
        <DropdownMenuItem>Rename</DropdownMenuItem>
        <DropdownMenuCheckboxItem checked>Pinned</DropdownMenuCheckboxItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem variant="destructive">Delete</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>,
  );
}

function openMenu() {
  fireEvent.pointerDown(screen.getByRole('button', { name: 'Actions' }), { button: 0 });
}

describe('DropdownMenu', () => {
  it('trigger exposes menu semantics and stays closed by default', () => {
    // Arrange + Act
    renderMenu();

    // Assert
    const trigger = screen.getByRole('button', { name: 'Actions' });
    expect(trigger).toHaveAttribute('aria-haspopup', 'menu');
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('menu')).toBeNull();
  });

  it('opens on pointer down and renders items with role=menuitem', async () => {
    // Arrange
    renderMenu();

    // Act
    openMenu();

    // Assert
    const menu = await screen.findByRole('menu');
    expect(menu).toBeInTheDocument();
    // Regular items expose role=menuitem, checkbox items role=menuitemcheckbox.
    expect(screen.getAllByRole('menuitem')).toHaveLength(2);
    expect(screen.getByRole('menuitemcheckbox', { name: 'Pinned' })).toHaveAttribute(
      'aria-checked',
      'true',
    );
    expect(screen.getByText('Session')).toBeInTheDocument();
  });

  it('links the open menu to its trigger via aria-controls / aria-labelledby', async () => {
    // Arrange
    renderMenu();
    const trigger = screen.getByRole('button', { name: 'Actions' });

    // Act
    openMenu();

    // Assert
    const menu = await screen.findByRole('menu');
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    expect(trigger.getAttribute('aria-controls')).toBe(menu.id);
    expect(menu).toHaveAttribute('aria-labelledby', trigger.id);
  });

  it('opens via keyboard (ArrowDown) for keyboard-only users', async () => {
    // Arrange
    renderMenu();
    const trigger = screen.getByRole('button', { name: 'Actions' });

    // Act
    fireEvent.keyDown(trigger, { key: 'ArrowDown' });

    // Assert
    expect(await screen.findByRole('menu')).toBeInTheDocument();
  });

  it('invokes onSelect and closes when an item is activated', async () => {
    // Arrange
    const onSelect = vi.fn();
    render(
      <DropdownMenu>
        <DropdownMenuTrigger>Actions</DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuItem onSelect={onSelect}>Rename</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>,
    );
    fireEvent.pointerDown(screen.getByRole('button', { name: 'Actions' }), { button: 0 });
    const item = await screen.findByRole('menuitem', { name: 'Rename' });

    // Act
    fireEvent.click(item);

    // Assert
    expect(onSelect).toHaveBeenCalledOnce();
    expect(screen.queryByRole('menu')).toBeNull();
  });

  it('closes on Escape and reports the closed state', async () => {
    // Arrange
    const onOpenChange = vi.fn();
    renderMenu(onOpenChange);
    const trigger = screen.getByRole('button', { name: 'Actions' });
    fireEvent.pointerDown(trigger, { button: 0 });
    const menu = await screen.findByRole('menu');

    // Act
    fireEvent.keyDown(menu, { key: 'Escape' });

    // Assert
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(screen.queryByRole('menu')).toBeNull();
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
  });
});
