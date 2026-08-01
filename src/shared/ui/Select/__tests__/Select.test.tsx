import { fireEvent, render, screen } from '@testing-library/react';
import { beforeAll, describe, expect, it, vi } from 'vitest';

import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '../Select';

// Radix Select relies on pointer-capture and scroll APIs that jsdom does not implement.
beforeAll(() => {
  window.HTMLElement.prototype.hasPointerCapture = vi.fn(() => false);
  window.HTMLElement.prototype.setPointerCapture = vi.fn();
  window.HTMLElement.prototype.releasePointerCapture = vi.fn();
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
});

function renderSelect(onValueChange = (_value: string) => {}) {
  return render(
    <Select onValueChange={onValueChange}>
      <SelectTrigger aria-label="Model">
        <SelectValue placeholder="Choose a model" />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          <SelectLabel>Models</SelectLabel>
          <SelectItem value="gpt-4o">GPT-4o</SelectItem>
          <SelectItem value="claude">Claude</SelectItem>
        </SelectGroup>
      </SelectContent>
    </Select>,
  );
}

function openSelect() {
  fireEvent.pointerDown(screen.getByRole('combobox'), { button: 0, pointerType: 'mouse' });
}

describe('Select', () => {
  it('renders a combobox trigger with the placeholder and collapsed state', () => {
    // Arrange + Act
    renderSelect();

    // Assert
    const trigger = screen.getByRole('combobox');
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByText('Choose a model')).toBeInTheDocument();
    expect(screen.queryByRole('listbox')).toBeNull();
  });

  it('opens on pointer down and lists options with role=option', async () => {
    // Arrange
    renderSelect();

    // Act
    openSelect();

    // Assert
    const listbox = await screen.findByRole('listbox');
    expect(listbox).toBeInTheDocument();
    expect(screen.getAllByRole('option')).toHaveLength(2);
    expect(screen.getByText('Models')).toBeInTheDocument();
  });

  it('links the listbox to the trigger via aria-controls', async () => {
    // Arrange
    renderSelect();
    const trigger = screen.getByRole('combobox');

    // Act
    openSelect();

    // Assert
    const listbox = await screen.findByRole('listbox');
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    expect(trigger.getAttribute('aria-controls')).toBe(listbox.id);
  });

  it('selects an option and reports its value', async () => {
    // Arrange
    const onValueChange = vi.fn();
    renderSelect(onValueChange);
    openSelect();
    const option = await screen.findByRole('option', { name: 'Claude' });

    // Act — simulate a real mouse gesture: after pressing the trigger, the
    // pointer moves to the option (>10px, so Radix's drag-open guard does not
    // swallow the pointerup) and the option sees a mouse pointerdown before
    // the pointerup that commits the selection. jsdom derives pageX/pageY
    // from clientX/clientY, so the distance must be expressed as client coords.
    const mouseAt = { button: 0, pointerType: 'mouse', clientX: 100, clientY: 100 };
    fireEvent.pointerDown(option, mouseAt);
    fireEvent.pointerMove(option, mouseAt);
    fireEvent.pointerUp(option, mouseAt);

    // Assert
    expect(onValueChange).toHaveBeenCalledOnce();
    expect(onValueChange).toHaveBeenCalledWith('claude');
    expect(screen.getByText('Claude')).toBeInTheDocument();
  });

  it('does not open when disabled', () => {
    // Arrange
    render(
      <Select disabled>
        <SelectTrigger aria-label="Model">
          <SelectValue placeholder="Choose a model" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="gpt-4o">GPT-4o</SelectItem>
        </SelectContent>
      </Select>,
    );

    // Act
    fireEvent.pointerDown(screen.getByRole('combobox'), { button: 0, pointerType: 'mouse' });

    // Assert
    expect(screen.queryByRole('listbox')).toBeNull();
  });
});
