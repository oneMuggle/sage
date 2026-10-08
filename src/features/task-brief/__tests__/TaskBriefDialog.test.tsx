import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../shared/lib/i18n', () => ({ useI18n: () => ({ locale: 'en' }) }));
vi.mock('../../../shared/api/projectApi', () => ({
  projectApi: { list: vi.fn().mockResolvedValue([{ id: 'project-a', name: 'Project A' }]) },
}));
import { TaskBriefDialog } from '../TaskBriefDialog';
const recommendation = {
  id: 'report',
  title: 'report',
  prompt: 'Prepare a report',
  icon: 'FileText',
  gradient: '',
};
beforeEach(() => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});
afterEach(() => vi.unstubAllGlobals());

describe('task brief submission', () => {
  it('passes the chosen project and never marks a failed start as complete', async () => {
    const submit = vi.fn().mockResolvedValue(false);
    const close = vi.fn();
    render(<TaskBriefDialog recommendation={recommendation} onSubmit={submit} onClose={close} />);
    await waitFor(() =>
      expect(screen.getByRole('option', { name: 'Project A' })).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByTestId('task-brief-project'), { target: { value: 'project-a' } });
    fireEvent.click(screen.getByTestId('task-brief-submit'));
    await waitFor(() =>
      expect(submit).toHaveBeenCalledWith(
        expect.stringContaining('Deliverable: docx'),
        'project-a',
        undefined,
      ),
    );
    expect(close).not.toHaveBeenCalled();
    expect(
      await screen.findByText('Task was not started. Check the configuration and retry.'),
    ).toBeInTheDocument();
  });
  it('does not start a task until a model is configured', () => {
    const submit = vi.fn();
    render(
      <TaskBriefDialog
        recommendation={recommendation}
        disabled
        onSubmit={submit}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByTestId('task-brief-submit')).toBeDisabled();
    fireEvent.click(screen.getByTestId('task-brief-submit'));
    expect(submit).not.toHaveBeenCalled();
  });
});
