import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import type { Message } from '../../../shared/lib/store';
import { MessageClientMeta } from '../MessageClientMeta';

const mocks = vi.hoisted(() => ({
  copyToClipboard: vi.fn(() => Promise.resolve(true)),
  openOfficeDocument: vi.fn(() => Promise.resolve()),
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

  it('opens office refs with the workspace recorded on the historical message', async () => {
    Object.defineProperty(window, 'electronAPI', {
      configurable: true,
      value: { office: { openOfficeDocument: mocks.openOfficeDocument } },
    });
    renderWithI18n(
      <MessageClientMeta
        message={message({
          client_meta: {
            file_refs: [],
            office_refs: [
              {
                doc_id: 'doc-1',
                doc_type: 'word',
                filename: '方案.docx',
                workspace_path: '/old/workspace',
              },
            ],
            knowledge_refs: [],
            attachments: [],
            images: [],
          },
        })}
        isUser
      />,
    );

    fireEvent.contextMenu(screen.getByTestId('message-office-ref'), {
      clientX: 3,
      clientY: 3,
    });
    fireEvent.click(await screen.findByRole('menuitem', { name: '打开' }));

    await waitFor(() =>
      expect(mocks.openOfficeDocument).toHaveBeenCalledWith(
        expect.objectContaining({ workspacePath: '/old/workspace', documentId: 'doc-1' }),
      ),
    );
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
