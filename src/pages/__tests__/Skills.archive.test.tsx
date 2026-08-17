import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { Skill } from '../../shared/api/types';
import { I18nProvider } from '../../shared/lib/i18n';
import Skills from '../Skills';

const listMock = vi.fn();
const archiveMock = vi.fn();

vi.mock('../../shared/api', () => ({
  skillsApi: {
    list: () => listMock(),
    toggle: vi.fn(),
    execute: vi.fn(),
    listSlashCommands: vi.fn().mockResolvedValue([]),
    delete: vi.fn(),
    archive: (name: string, archived: boolean) => archiveMock(name, archived),
  },
}));

const makeSkill = (
  name: string,
  lifecycle: 'active' | 'stale' | 'archived' = 'stale',
  source: 'builtin' | 'skillmd' = 'skillmd',
): Skill => ({
  name,
  description: `${name} desc`,
  triggers: [],
  parameters: {},
  examples: [],
  enabled: true,
  usage_count: 0,
  source,
  lifecycle,
});

function renderSkills() {
  return render(
    <I18nProvider defaultLocale="zh">
      <Skills />
    </I18nProvider>,
  );
}

describe('Skills page — archive flow', () => {
  afterEach(() => {
    listMock.mockReset();
    archiveMock.mockReset();
    vi.restoreAllMocks();
  });

  it('stale 技能点「归档」→ skillsApi.archive(name, true) + badge 变「已归档」', async () => {
    archiveMock.mockResolvedValue(makeSkill('travel', 'archived'));
    listMock.mockResolvedValue([makeSkill('travel', 'stale')]);
    renderSkills();
    await waitFor(() => expect(screen.getByText('已冷')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /归档 travel/i }));

    await waitFor(() => expect(archiveMock).toHaveBeenCalledWith('travel', true));
    await waitFor(() => expect(screen.getByText('已归档')).toBeInTheDocument());
  });

  it('archived 技能点「取消归档」→ skillsApi.archive(name, false)', async () => {
    archiveMock.mockResolvedValue(makeSkill('travel', 'stale'));
    listMock.mockResolvedValue([makeSkill('travel', 'archived')]);
    renderSkills();
    await waitFor(() => expect(screen.getByText('已归档')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /取消归档 travel/i }));

    await waitFor(() => expect(archiveMock).toHaveBeenCalledWith('travel', false));
  });

  it('归档失败 → 回滚到原 lifecycle（optimistic rollback）', async () => {
    archiveMock.mockRejectedValue(new Error('persist failed'));
    listMock.mockResolvedValue([makeSkill('travel', 'stale')]);
    renderSkills();
    await waitFor(() => expect(screen.getByText('已冷')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /归档 travel/i }));

    await waitFor(() => expect(archiveMock).toHaveBeenCalled());
    // 回滚后仍是「已冷」，未停留在 optimistic 的「已归档」
    await waitFor(() => expect(screen.getByText('已冷')).toBeInTheDocument());
    expect(screen.queryByText('已归档')).not.toBeInTheDocument();
  });
});
