import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const mockList = vi.fn();

vi.mock('../../../entities/scheduled/taskStore', () => {
  const state = {
    tasks: [],
    loading: false,
    error: null,
    load: vi.fn(),
    create: vi.fn().mockResolvedValue({}),
    update: vi.fn().mockResolvedValue({}),
    delete: vi.fn(),
    runNow: vi.fn(),
  };
  const hook = (sel?: (s: unknown) => unknown) => (sel ? sel(state) : state);
  return {
    useScheduledTaskStore: Object.assign(hook, { getState: () => state, setState: vi.fn() }),
  };
});

vi.mock('../../../shared/api/skillsApi', () => ({
  skillsApi: { list: () => mockList() },
}));

import type { Skill } from '../../../shared/api/types';
import { I18nProvider } from '../../../shared/lib/i18n';
import { CreateTaskModal } from '../CreateTaskModal';

function skill(name: string, enabled = true): Skill {
  return {
    name,
    description: name,
    triggers: [],
    parameters: {},
    examples: [],
    enabled,
    usage_count: 0,
  } as Skill;
}

function renderModal(): void {
  render(
    <I18nProvider>
      <CreateTaskModal open={true} onClose={vi.fn()} sessionId="s-1" />
    </I18nProvider>,
  );
}

function submitButton(): HTMLButtonElement {
  const buttons = screen.getAllByRole('button');
  const submit = buttons.find((b) => b.getAttribute('type') === 'submit');
  return submit as HTMLButtonElement;
}

describe('CreateTaskModal 技能引用', () => {
  it('引用未注册技能时给出明确提示并要求确认，不静默丢弃', async () => {
    mockList.mockResolvedValue([skill('writer'), skill('search', false)]);
    renderModal();
    await waitFor(() => expect(mockList).toHaveBeenCalled());

    fireEvent.change(screen.getByPlaceholderText(/scheduled\.field\.name|Task name|任务名称/i), {
      target: { value: '每日汇总' },
    });
    const textarea = document.querySelector('textarea') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: '用 /ghost 汇总' } });

    const warning = await screen.findByTestId('scheduled-skill-warning');
    expect(warning.textContent).toContain('/ghost');
    expect(submitButton().disabled).toBe(true);

    fireEvent.click(screen.getByTestId('scheduled-skill-ack'));
    await waitFor(() => expect(submitButton().disabled).toBe(false));
    // 引用仍保留在正文里，没有被自动改写
    expect(textarea.value).toContain('/ghost');
  });

  it('技能列表不可用时提示无法校验，且不阻塞保存', async () => {
    mockList.mockRejectedValue(new Error('ipc down'));
    renderModal();
    await waitFor(() => expect(mockList).toHaveBeenCalled());
    const notice = await screen.findByTestId('scheduled-skill-unavailable');
    expect(notice.textContent).toBeTruthy();
    expect(screen.queryByTestId('scheduled-skill-warning')).toBeNull();
  });

  it('从选择器插入已注册技能会写入正文并显示为引用', async () => {
    mockList.mockResolvedValue([skill('writer')]);
    renderModal();
    await waitFor(() => expect(mockList).toHaveBeenCalled());
    fireEvent.change(screen.getByTestId('scheduled-skill-select'), {
      target: { value: 'writer' },
    });
    const textarea = document.querySelector('textarea') as HTMLTextAreaElement;
    await waitFor(() => expect(textarea.value).toContain('/writer'));
    expect(screen.getByTestId('scheduled-skill-chip').textContent).toContain('/writer');
  });
});
