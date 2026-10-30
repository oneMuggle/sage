import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import SkillCard from '../SkillCard';

const mocks = vi.hoisted(() => ({
  copyToClipboard: vi.fn(() => Promise.resolve(true)),
  confirmDialog: vi.fn(),
}));

vi.mock('../../../shared/lib/clipboard', () => ({
  copyToClipboard: mocks.copyToClipboard,
}));

vi.mock('../../../shared/ui/ConfirmDialog/confirmService', () => ({
  confirmDialog: mocks.confirmDialog,
}));

const base = {
  name: 'search',
  description: '搜索网络信息并整理结果',
  triggers: ['搜索', '查找'],
  enabled: true,
  usage_count: 3,
  source: 'skillmd' as const,
  body: '# Search skill',
  lifecycle: 'active' as const,
  pinned: false,
};

function renderCard(overrides: Partial<Parameters<typeof SkillCard>[0]> = {}) {
  return render(
    <I18nProvider defaultLocale="zh">
      <SkillCard
        {...base}
        onToggle={vi.fn()}
        onPin={vi.fn()}
        onArchive={vi.fn()}
        onDelete={vi.fn()}
        {...overrides}
      />
    </I18nProvider>,
  );
}

function openMenu() {
  fireEvent.contextMenu(screen.getByText('search'), { clientX: 4, clientY: 4 });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('SkillCard — context menu', () => {
  it('pins through the existing handler', async () => {
    const onPin = vi.fn();
    renderCard({ onPin });

    openMenu();
    fireEvent.click(await screen.findByRole('menuitem', { name: '钉住技能' }));

    expect(onPin).toHaveBeenCalledWith('search', true);
  });

  it('archives through the existing handler', async () => {
    const onArchive = vi.fn();
    renderCard({ onArchive });

    openMenu();
    fireEvent.click(await screen.findByRole('menuitem', { name: '归档技能' }));

    expect(onArchive).toHaveBeenCalledWith('search', true);
  });

  it('copies the prompt template body', async () => {
    renderCard();

    openMenu();
    fireEvent.click(await screen.findByRole('menuitem', { name: '复制提示词模板' }));

    expect(mocks.copyToClipboard).toHaveBeenCalledWith('# Search skill', expect.any(Object));
  });

  it('confirms before deleting', async () => {
    const onDelete = vi.fn();
    mocks.confirmDialog.mockResolvedValueOnce(true);
    renderCard({ onDelete });

    openMenu();
    fireEvent.click(await screen.findByRole('menuitem', { name: '删除技能…' }));

    await waitFor(() => expect(onDelete).toHaveBeenCalledWith('search'));
  });
});
