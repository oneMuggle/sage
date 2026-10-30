import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { PromptTemplatesTab } from '../PromptTemplatesTab';

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  remove: vi.fn(),
  confirmDialog: vi.fn(),
}));

vi.mock('../../../shared/api/promptApi', () => ({
  promptApi: {
    list: () => mocks.list(),
    create: vi.fn(),
    update: vi.fn(),
    remove: (...args: unknown[]) => mocks.remove(...args),
    exportTemplates: vi.fn(),
    importTemplates: vi.fn(),
  },
}));

vi.mock('../../../shared/ui/ConfirmDialog/confirmService', () => ({
  confirmDialog: mocks.confirmDialog,
}));

const template = {
  id: 'tpl-1',
  name: '周报模板',
  description: '每周工作汇总',
  content: '请总结本周工作：\n{content}',
  created_at: 1,
  updated_at: 1,
};

function renderTab() {
  return render(
    <I18nProvider defaultLocale="zh">
      <PromptTemplatesTab />
    </I18nProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.list.mockResolvedValue([template]);
  mocks.remove.mockResolvedValue(undefined);
});

describe('PromptTemplatesTab — context menu', () => {
  it('opens edit form and confirms deletion from the row menu', async () => {
    mocks.confirmDialog.mockResolvedValueOnce(true);
    renderTab();

    const item = await screen.findByTestId('prompts-item');
    fireEvent.contextMenu(item, { clientX: 4, clientY: 4 });

    expect(await screen.findByRole('menuitem', { name: '编辑模板' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: '复制模板内容' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('menuitem', { name: '编辑模板' }));
    expect(screen.getByTestId('prompts-form')).toBeInTheDocument();

    fireEvent.contextMenu(screen.getByTestId('prompts-item'), { clientX: 4, clientY: 4 });
    fireEvent.click(await screen.findByRole('menuitem', { name: '删除模板…' }));

    await waitFor(() => expect(mocks.remove).toHaveBeenCalledWith('tpl-1'));
    expect(mocks.confirmDialog.mock.calls[0][0]).toMatchObject({ danger: true });
  });
});
