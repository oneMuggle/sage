import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import type { Message } from '../../../shared/lib/store';
import { MessageClientMeta } from '../MessageClientMeta';

const mocks = vi.hoisted(() => ({
  copyToClipboard: vi.fn(() => Promise.resolve(true)),
}));

vi.mock('../../../shared/lib/clipboard', () => ({
  copyToClipboard: mocks.copyToClipboard,
}));

vi.mock('../../../shared/lib/workspaceContext', () => ({
  useCurrentWorkspace: () => '/workspace/ws',
}));

function message(overrides: Partial<Message> = {}): Message {
  return {
    id: 'm-1',
    session_id: 's-1',
    role: 'user',
    content: '带引用的问题',
    created_at: 1_750_000_000_000,
    client_meta: {
      file_refs: [{ path: 'src/app/main.ts', name: 'main.ts' }],
      office_refs: [],
      knowledge_refs: [],
      attachments: [],
      images: [],
    },
    ...overrides,
  };
}

const renderWithI18n = (ui: React.ReactElement) =>
  render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);

describe('MessageClientMeta — context menu', () => {
  it('copies the full path and file name from a file reference chip', async () => {
    renderWithI18n(<MessageClientMeta message={message()} isUser />);

    fireEvent.contextMenu(screen.getByTestId('message-file-ref'), { clientX: 3, clientY: 3 });
    fireEvent.click(await screen.findByRole('menuitem', { name: '复制路径' }));
    expect(mocks.copyToClipboard).toHaveBeenCalledWith('src/app/main.ts', expect.any(Object));

    fireEvent.contextMenu(screen.getByTestId('message-file-ref'), { clientX: 3, clientY: 3 });
    fireEvent.click(await screen.findByRole('menuitem', { name: '复制文件名' }));
    expect(mocks.copyToClipboard).toHaveBeenCalledWith('main.ts', expect.any(Object));
  });

  it('opens image attachments in the lightbox from the menu', async () => {
    renderWithI18n(
      <MessageClientMeta
        message={message()}
        isUser
        attachments={[
          {
            name: 'diagram.png',
            size: 10,
            type: 'image/png',
            dataUrl: 'data:image/png;base64,AAA',
          },
        ]}
      />,
    );

    fireEvent.contextMenu(screen.getByTestId('message-attachment-ref'), {
      clientX: 3,
      clientY: 3,
    });
    fireEvent.click(await screen.findByRole('menuitem', { name: '查看大图' }));

    expect(screen.getByTestId('lightbox')).toBeInTheDocument();
  });
});
