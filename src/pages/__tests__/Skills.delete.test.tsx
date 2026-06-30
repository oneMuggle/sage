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

  it('clicks delete → confirm → calls skillsApi.delete', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    deleteMock.mockResolvedValue({ deleted: true, name: 'web-search' });

    listMock.mockResolvedValueOnce([makeSkill('web-search')]);
    renderSkills();
    await waitFor(() => expect(screen.getByText('web-search')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /删除.*web-search/i }));

    await waitFor(() => expect(deleteMock).toHaveBeenCalledWith('web-search'));
  });

  it('cancels confirm → does NOT call delete', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    listMock.mockResolvedValue([makeSkill('web-search')]);
    renderSkills();
    await waitFor(() => expect(screen.getByText('web-search')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /删除.*web-search/i }));

    expect(deleteMock).not.toHaveBeenCalled();
  });

  it('delete fails → keeps original list', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    deleteMock.mockRejectedValue(new Error('cannot delete builtin'));

    listMock.mockResolvedValue([makeSkill('web-search')]);
    renderSkills();
    await waitFor(() => expect(screen.getByText('web-search')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /删除.*web-search/i }));

    await waitFor(() => expect(deleteMock).toHaveBeenCalled());
    // skill 仍在列表里（删除失败回滚 optimistic）
    await waitFor(() => expect(screen.getByText('web-search')).toBeInTheDocument());
  });
});
