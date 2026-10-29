import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { FileAttachment } from '../FileAttachment';
import { KnowledgeChip } from '../KnowledgeChip';

const mocks = vi.hoisted(() => ({
  copyToClipboard: vi.fn(() => Promise.resolve(true)),
}));

vi.mock('../../../shared/lib/clipboard', () => ({
  copyToClipboard: mocks.copyToClipboard,
}));

const renderWithI18n = (ui: React.ReactElement) =>
  render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);

describe('FileAttachment — context menu', () => {
  it('copies the file name and can remove the attachment', async () => {
    const onRemove = vi.fn();
    renderWithI18n(
      <FileAttachment name="报告.pdf" size={2048} type="application/pdf" onRemove={onRemove} />,
    );

    fireEvent.contextMenu(screen.getByText('报告.pdf'), { clientX: 2, clientY: 2 });
    fireEvent.click(await screen.findByRole('menuitem', { name: '复制文件名' }));
    expect(mocks.copyToClipboard).toHaveBeenCalledWith('报告.pdf', expect.any(Object));

    fireEvent.contextMenu(screen.getByText('报告.pdf'), { clientX: 2, clientY: 2 });
    fireEvent.click(await screen.findByRole('menuitem', { name: '移除' }));
    expect(onRemove).toHaveBeenCalledTimes(1);
  });

  it('omits the remove item when no handler is provided', async () => {
    renderWithI18n(<FileAttachment name="a.txt" size={10} type="text/plain" />);

    fireEvent.contextMenu(screen.getByText('a.txt'), { clientX: 2, clientY: 2 });
    await screen.findByRole('menuitem', { name: '复制文件名' });

    expect(screen.queryByRole('menuitem', { name: '移除' })).toBeNull();
  });
});

describe('KnowledgeChip — context menu', () => {
  it('copies the knowledge title', async () => {
    renderWithI18n(<KnowledgeChip title="架构说明" />);

    fireEvent.contextMenu(screen.getByText('架构说明'), { clientX: 2, clientY: 2 });
    fireEvent.click(await screen.findByRole('menuitem', { name: '复制文件名' }));

    expect(mocks.copyToClipboard).toHaveBeenCalledWith('架构说明', expect.any(Object));
  });
});
