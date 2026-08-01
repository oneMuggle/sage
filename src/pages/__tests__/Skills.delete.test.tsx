import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { Skill } from '../../shared/api/types';
import { I18nProvider } from '../../shared/lib/i18n';
import Skills from '../Skills';

const listMock = vi.fn();
const deleteMock = vi.fn();

vi.mock('../../shared/api', () => ({
  skillsApi: {
    list: () => listMock(),
    toggle: vi.fn(),
    execute: vi.fn(),
    listSlashCommands: vi.fn().mockResolvedValue([]),
    delete: (name: string) => deleteMock(name),
  },
}));

const makeSkill = (name: string, source: 'builtin' | 'skillmd' = 'skillmd'): Skill => ({
  name,
  description: `${name} desc`,
  triggers: [],
  parameters: {},
  examples: [],
  enabled: true,
  usage_count: 0,
  source,
});

function renderSkills() {
  return render(
    <I18nProvider defaultLocale="zh">
      <Skills />
    </I18nProvider>,
  );
}

describe('Skills page — delete flow', () => {
  afterEach(() => {
    listMock.mockReset();
    deleteMock.mockReset();
    vi.restoreAllMocks();
  });

  it('does NOT show delete button on builtin skills', async () => {
    listMock.mockResolvedValue([makeSkill('coder', 'builtin')]);
    renderSkills();
    await waitFor(() => expect(screen.getByText('coder')).toBeInTheDocument());

    // builtin 不应有 delete 按钮
    expect(screen.queryByRole('button', { name: /删除.*coder/i })).toBeNull();
  });

  it('two-step confirm: second click calls skillsApi.delete (U12)', async () => {
    deleteMock.mockResolvedValue({ deleted: true, name: 'web-search' });

    listMock.mockResolvedValueOnce([makeSkill('web-search')]);
    renderSkills();
    await waitFor(() => expect(screen.getByText('web-search')).toBeInTheDocument());

    // 第一次点击：仅 armed，不删除
    fireEvent.click(screen.getByRole('button', { name: /删除技能 web-search/i }));
    expect(deleteMock).not.toHaveBeenCalled();

    // 第二次点击：确认删除
    fireEvent.click(screen.getByRole('button', { name: /确认删除 web-search/i }));
    await waitFor(() => expect(deleteMock).toHaveBeenCalledWith('web-search'));
  });

  it('single click only arms, does NOT call delete (U12)', async () => {
    listMock.mockResolvedValue([makeSkill('web-search')]);
    renderSkills();
    await waitFor(() => expect(screen.getByText('web-search')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /删除技能 web-search/i }));

    expect(deleteMock).not.toHaveBeenCalled();
  });

  it('delete fails → keeps original list', async () => {
    deleteMock.mockRejectedValue(new Error('cannot delete builtin'));

    listMock.mockResolvedValue([makeSkill('web-search')]);
    renderSkills();
    await waitFor(() => expect(screen.getByText('web-search')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /删除技能 web-search/i }));
    fireEvent.click(screen.getByRole('button', { name: /确认删除 web-search/i }));

    await waitFor(() => expect(deleteMock).toHaveBeenCalled());
    // skill 仍在列表里（删除失败回滚 optimistic）
    await waitFor(() => expect(screen.getByText('web-search')).toBeInTheDocument());
  });
});
