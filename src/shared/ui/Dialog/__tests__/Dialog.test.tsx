import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '../Dialog';

function renderDialog(onOpenChange = (_open: boolean) => {}) {
  return render(
    <Dialog onOpenChange={onOpenChange}>
      <DialogTrigger>Open export</DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Export session</DialogTitle>
          <DialogDescription>Choose a format for the exported file.</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <DialogClose asChild>
            <button type="button">Cancel</button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>,
  );
}

describe('Dialog', () => {
  it('does not render dialog content while closed', () => {
    // Arrange + Act
    renderDialog();

    // Assert
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('opens on trigger click with role=dialog and modal data-state', async () => {
    // Arrange
    renderDialog();

    // Act
    fireEvent.click(screen.getByText('Open export'));

    // Assert
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveAttribute('data-state', 'open');
    expect(screen.getByText('Export session')).toBeVisible();
  });

  it('links the dialog to its title and description via aria attributes', async () => {
    // Arrange
    renderDialog();

    // Act
    fireEvent.click(screen.getByText('Open export'));

    // Assert
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveAttribute('aria-labelledby', screen.getByText('Export session').id);
    expect(dialog).toHaveAttribute(
      'aria-describedby',
      screen.getByText('Choose a format for the exported file.').id,
    );
  });

  it('closes on Escape', async () => {
    // Arrange
    const onOpenChange = vi.fn();
    renderDialog(onOpenChange);
    fireEvent.click(screen.getByText('Open export'));
    const dialog = await screen.findByRole('dialog');

    // Act
    fireEvent.keyDown(dialog, { key: 'Escape' });

    // Assert
    expect(await screen.findByText('Open export')).toBeInTheDocument();
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('renders a labelled close button that closes the dialog', async () => {
    // Arrange
    renderDialog();
    fireEvent.click(screen.getByText('Open export'));
    await screen.findByRole('dialog');

    // Act
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));

    // Assert
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('omits the close button when showCloseButton is false', async () => {
    // Arrange
    render(
      <Dialog defaultOpen>
        <DialogContent showCloseButton={false}>
          <DialogTitle>Confirm deletion</DialogTitle>
        </DialogContent>
      </Dialog>,
    );

    // Act
    await screen.findByRole('dialog');

    // Assert
    expect(screen.queryByRole('button', { name: 'Close' })).toBeNull();
  });
});
