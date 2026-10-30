import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import type { Message as MessageType } from '../../../shared/lib/store';
import { Message } from '../Message';

const mocks = vi.hoisted(() => ({
  confirmDialog: vi.fn(),
  copyToClipboard: vi.fn(() => Promise.resolve(true)),
  getQuotableSelection: vi.fn(),
}));

vi.mock('../../../shared/ui/ConfirmDialog/confirmService', () => ({
  confirmDialog: mocks.confirmDialog,
}));

vi.mock('../../../shared/lib/clipboard', () => ({
  copyToClipboard: mocks.copyToClipboard,
}));

vi.mock('../../../features/chat/selectionQuote', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../features/chat/selectionQuote')>();
  return { ...actual, getQuotableSelection: mocks.getQuotableSelection };
});

const msg = (id: string, role: MessageType['role'], content = '右键菜单测试消息'): MessageType => ({
  id,
  session_id: 's-1',
  role,
  content,
  created_at: 1_750_000_000_000,
});

const renderMessage = (ui: React.ReactElement) =>
  render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);

function rightClickMessage(content = '右键菜单测试消息') {
  fireEvent.contextMenu(screen.getByText(content), { clientX: 30, clientY: 40 });
}

describe('Message — context menu', () => {
  it('opens the user message menu with edit/resend and delete', async () => {
    renderMessage(
      <Message
        message={msg('u-1', 'user')}
        onQuote={vi.fn()}
        onEditResend={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    rightClickMessage();

    expect(await screen.findByRole('menuitem', { name: '复制' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: '编辑并重新发送' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: '引用到输入框' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: '删除消息…' })).toBeInTheDocument();
  });

  it('copies the message body through the shared clipboard util', async () => {
    renderMessage(<Message message={msg('u-1', 'user', '复制我')} />);

    rightClickMessage('复制我');
    fireEvent.click(await screen.findByRole('menuitem', { name: '复制' }));

    await waitFor(() =>
      expect(mocks.copyToClipboard).toHaveBeenCalledWith('复制我', expect.any(Object)),
    );
  });

  it('regenerates assistant answers', async () => {
    const onRegenerate = vi.fn();
    renderMessage(<Message message={msg('a-1', 'assistant')} onRegenerate={onRegenerate} />);

    rightClickMessage();
    fireEvent.click(await screen.findByRole('menuitem', { name: '重新生成' }));

    expect(onRegenerate).toHaveBeenCalledWith('a-1');
  });

  it('disables regeneration while streaming', async () => {
    const onRegenerate = vi.fn();
    renderMessage(
      <Message
        message={msg('a-2', 'assistant', '正在生成的内容')}
        isStreaming
        onRegenerate={onRegenerate}
      />,
    );

    rightClickMessage('正在生成的内容');
    fireEvent.click(await screen.findByRole('menuitem', { name: '重新生成' }));

    expect(onRegenerate).not.toHaveBeenCalled();
  });

  it('offers selection actions when text is selected inside the bubble', async () => {
    mocks.getQuotableSelection.mockReturnValue({ text: '选中的一段', rect: null });
    const onQuoteSelection = vi.fn();
    renderMessage(
      <Message
        message={msg('a-3', 'assistant')}
        onQuote={vi.fn()}
        onQuoteSelection={onQuoteSelection}
      />,
    );

    rightClickMessage();
    expect(await screen.findByRole('menuitem', { name: '复制选区' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('menuitem', { name: '引用选区到输入框' }));

    expect(onQuoteSelection).toHaveBeenCalledWith('选中的一段');
  });

  it('confirms before deleting a message', async () => {
    const onDelete = vi.fn();
    mocks.confirmDialog.mockResolvedValueOnce(true);
    renderMessage(<Message message={msg('u-2', 'user')} onDelete={onDelete} />);

    rightClickMessage();
    fireEvent.click(await screen.findByRole('menuitem', { name: '删除消息…' }));

    await waitFor(() => expect(onDelete).toHaveBeenCalledWith('u-2'));
    expect(mocks.confirmDialog.mock.calls[0][0]).toMatchObject({ danger: true });
  });

  it('opens the table menu instead of the message menu on table right click', async () => {
    const content = ['| 列A | 列B |', '| --- | --- |', '| 1 | 2 |'].join('\n');
    renderMessage(<Message message={msg('a-4', 'assistant', content)} onRegenerate={vi.fn()} />);

    fireEvent.contextMenu(await screen.findByText('列A'), { clientX: 10, clientY: 10 });

    expect(await screen.findByRole('menuitem', { name: '复制表格（TSV）' })).toBeInTheDocument();
    expect(screen.queryByRole('menuitem', { name: '重新生成' })).toBeNull();
  });
});
