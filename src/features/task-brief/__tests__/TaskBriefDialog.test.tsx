import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../shared/lib/i18n', () => ({ useI18n: () => ({ locale: 'en' }) }));
vi.mock('../../../shared/api/projectApi', () => ({
  projectApi: { list: vi.fn().mockResolvedValue([{ id: 'project-a', name: 'Project A' }]) },
}));
import {
  TaskBriefDialog,
  formatTaskBriefJson,
  formatTaskBriefMarkdown,
} from '../TaskBriefDialog';
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

  it('formats and copies task brief as Markdown and JSON', async () => {
    const brief = {
      scenario: 'report' as const,
      goal: '撰写季度复盘',
      audience: '管理层',
      sources: 'Q3 财务报表',
      format: 'docx' as const,
      requirements: '不超过 5 页',
      projectId: 'p1',
    };
    const md = formatTaskBriefMarkdown(brief, 'ep1::gpt-4o');
    expect(md).toContain('# 任务交付简报 (Task Deliverable Brief)');
    expect(md).toContain('撰写季度复盘');

    const parsed = JSON.parse(formatTaskBriefJson(brief, ''));
    expect(parsed.brief.goal).toBe('撰写季度复盘');
    expect(parsed.modelId).toBeNull();

    render(
      <TaskBriefDialog
        recommendation={recommendation}
        onSubmit={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId('task-brief-copy-md'));
    expect(screen.getByTestId('task-brief-copy-md').textContent).toContain('已复制 MD');
    fireEvent.click(screen.getByTestId('task-brief-copy-json'));
    expect(screen.getByTestId('task-brief-copy-json').textContent).toContain('已复制 JSON');
  });
});
