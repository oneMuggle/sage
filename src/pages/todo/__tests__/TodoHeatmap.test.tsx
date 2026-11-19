import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ heatmap: vi.fn() }));

vi.mock('../../../shared/api/todoClient', () => ({
  todoClient: { heatmap: mocks.heatmap },
}));

import { TodoHeatmap } from '../TodoHeatmap';

beforeEach(() => {
  mocks.heatmap.mockReset();
});

describe('TodoHeatmap', () => {
  it('renders the total and one cell per day', async () => {
    const days = Array.from({ length: 7 }, (_, i) => ({
      date: `2026-11-${String(12 + i).padStart(2, '0')}`,
      count: i === 6 ? 3 : 0,
    }));
    mocks.heatmap.mockResolvedValue({ days, total: 3, max: 3 });

    render(<TodoHeatmap days={7} />);

    const heatmap = await screen.findByTestId('todo-heatmap');
    expect(heatmap.textContent).toContain('完成');
    expect(heatmap.textContent).toContain('3');
    expect(heatmap.querySelectorAll('[data-count]')).toHaveLength(7);
  });

  it('shows an error when the request fails', async () => {
    mocks.heatmap.mockRejectedValue(new Error('boom'));
    render(<TodoHeatmap days={7} />);
    expect((await screen.findByTestId('todo-heatmap-error')).textContent).toContain('boom');
  });
});
