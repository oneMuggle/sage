import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import type { Session } from '../../../shared/lib/store';
import { SessionItem } from '../SessionItem';

const mocks = vi.hoisted(() => ({
  confirmDialog: vi.fn(),
  copyToClipboard: vi.fn(() => Promise.resolve(true)),
  setPinned: vi.fn(() => Promise.resolve()),
  exportHtml: vi.fn(),
  exportMarkdown: vi.fn(),
}));

vi.mock('../../../shared/ui/ConfirmDialog/confirmService', () => ({
  confirmDialog: mocks.confirmDialog,
}));

vi.mock('../../../shared/lib/clipboard', () => ({
  copyToClipboard: mocks.copyToClipboard,
}));

vi.mock('../../../shared/api/sessionApi', () => ({
  sessionApi: {
    setPinned: mocks.setPinned,
    exportHtml: mocks.exportHtml,
    exportMarkdown: mocks.exportMarkdown,
  },
  downloadHtmlFile: vi.fn(),
  downloadMarkdownFile: vi.fn(),
}));

const baseSession = (overrides: Partial<Session> = {}): Session => ({
  id: 's-1',
  title: '普通会话',
  created_at: 1_750_000_000_000,
  updated_at: 1_750_000_000_000,
  last_message_at: null,
  message_count: 0,
  is_pinned: false,
  ...overrides,
});

function renderItem(options: { session?: Partial<Session>; onDelete?: () => void } = {}) {
  return render(
    <I18nProvider defaultLocale="zh">
      <SessionItem
        session={baseSession(options.session)}
        isActive={false}
        onSelect={vi.fn()}
        onDelete={options.onDelete ?? vi.fn()}
        onRename={vi.fn().mockResolvedValue(undefined)}
      />
    </I18nProvider>,
  );
}

function openMenu() {
  fireEvent.contextMenu(screen.getByTestId('session-item'), { clientX: 12, clientY: 24 });
}

describe('SessionItem — context menu', () => {
  it('opens the session context menu on right click', async () => {
    renderItem();
    openMenu();

    expect(await screen.findByRole('menuitem', { name: '打开会话' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: '重命名' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: '置顶会话' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: '导出 Markdown' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: '导出 HTML' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: '删除会话…' })).toBeInTheDocument();
  });

  it('reflects pin state and fork metadata', async () => {
    renderItem({ session: { is_pinned: true, fork_root: 'root-1' } });
    openMenu();

    expect(await screen.findByRole('menuitem', { name: '取消置顶' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: '查看分叉树' })).toBeInTheDocument();
  });

  it('enters inline rename mode from the menu', async () => {
    renderItem();
    openMenu();

    fireEvent.click(await screen.findByRole('menuitem', { name: '重命名' }));

    expect(screen.getByTestId('rename-session-input')).toBeInTheDocument();
  });

  it('toggles pin through the existing handler', async () => {
    renderItem();
    openMenu();

    fireEvent.click(await screen.findByRole('menuitem', { name: '置顶会话' }));

    await waitFor(() => expect(mocks.setPinned).toHaveBeenCalledWith('s-1', true));
  });

  it('copies the session title', async () => {
    renderItem();
    openMenu();

    fireEvent.click(await screen.findByRole('menuitem', { name: '复制标题' }));

    await waitFor(() =>
      expect(mocks.copyToClipboard).toHaveBeenCalledWith('普通会话', expect.any(Object)),
    );
  });

  it('asks for confirmation before deleting and honors cancel', async () => {
    const onDelete = vi.fn();
    mocks.confirmDialog.mockResolvedValueOnce(false);
    renderItem({ onDelete });
    openMenu();

    fireEvent.click(await screen.findByRole('menuitem', { name: '删除会话…' }));

    await waitFor(() => expect(mocks.confirmDialog).toHaveBeenCalledTimes(1));
    expect(mocks.confirmDialog.mock.calls[0][0]).toMatchObject({ danger: true });
    expect(onDelete).not.toHaveBeenCalled();
  });

  it('deletes after confirmation', async () => {
    const onDelete = vi.fn();
    mocks.confirmDialog.mockResolvedValueOnce(true);
    renderItem({ onDelete });
    openMenu();

    fireEvent.click(await screen.findByRole('menuitem', { name: '删除会话…' }));

    await waitFor(() => expect(onDelete).toHaveBeenCalledTimes(1));
  });

  it('does not open the menu while the inline rename input is active', () => {
    renderItem();
    fireEvent.click(screen.getByTestId('rename-session'));
    expect(screen.getByTestId('rename-session-input')).toBeInTheDocument();

    openMenu();

    expect(screen.queryByRole('menu')).toBeNull();
  });
});
