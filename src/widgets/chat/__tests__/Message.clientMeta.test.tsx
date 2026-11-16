/**
 * 用户消息引用信息回显 —— 附件 / @ 文件引用 / office 引用 / 知识库引用。
 * client_meta 由后端 get_messages 回读，刷新会话后仍应渲染。
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import type { Message as MessageType } from '../../../shared/lib/store';
import { Message } from '../Message';

// 附件卡片点击预览 PDF 时经 IPC 拉媒体 blob；测试内返回合成 blob URL。
vi.mock('../../../shared/api/mediaApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../shared/api/mediaApi')>();
  return {
    ...actual,
    fetchMediaBlobUrl: vi.fn().mockResolvedValue('blob:pdf-1'),
    revokeMediaBlobUrl: vi.fn(),
  };
});

const renderWithI18n = (ui: React.ReactElement) =>
  render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);

const makeUserMsg = (patch: Partial<MessageType> = {}): MessageType => ({
  id: 'u1',
  session_id: 's1',
  role: 'user',
  content: '看看这些资料',
  created_at: 0,
  ...patch,
});

describe('Message — user client_meta refs', () => {
  it('renders file refs, office refs, attachments and knowledge refs from client_meta', () => {
    renderWithI18n(
      <Message
        message={makeUserMsg({
          client_meta: {
            file_refs: [{ path: 'src/App.tsx', name: 'App.tsx' }],
            office_refs: [{ doc_id: 'doc-1', doc_type: 'pdf', filename: 'q3.pdf' }],
            attachments: [{ name: 'data.xlsx', size: 2048, type: 'application/vnd.ms-excel' }],
            images: [{ name: 'chart.png', size: 512, type: 'image/png' }],
            knowledge_refs: [{ id: 'k1', title: '写作规范' }],
          },
        })}
      />,
    );

    expect(screen.getByTestId('message-client-meta')).toBeInTheDocument();
    expect(screen.getByText('src/App.tsx')).toBeInTheDocument();
    expect(screen.getByText('q3.pdf')).toBeInTheDocument();
    expect(screen.getByText('data.xlsx')).toBeInTheDocument();
    expect(screen.getByText('chart.png')).toBeInTheDocument();
    expect(screen.getByText('写作规范')).toBeInTheDocument();
  });

  it('renders nothing when the user message has no client_meta', () => {
    renderWithI18n(<Message message={makeUserMsg()} />);
    expect(screen.queryByTestId('message-client-meta')).not.toBeInTheDocument();
  });

  it('keeps supporting the legacy attachments prop map', () => {
    renderWithI18n(
      <Message
        message={makeUserMsg()}
        attachments={[{ name: 'legacy.docx', size: 1, type: 'application/msword' }]}
      />,
    );
    expect(screen.getByText('legacy.docx')).toBeInTheDocument();
  });

  it('renders per-attachment status icons and summary from client_meta.attachments_status', () => {
    renderWithI18n(
      <Message
        message={makeUserMsg({
          client_meta: {
            attachments: [
              { name: 'app.py', size: 128, type: 'text/x-python' },
              { name: 'data.csv', size: 64, type: 'text/csv' },
            ],
            attachments_status: [
              {
                media_id: 'm1',
                filename: 'app.py',
                mime_type: 'text/x-python',
                status: 'ok',
                mode: 'full',
                chars: 1234,
              },
              {
                media_id: 'm2',
                filename: 'data.csv',
                mime_type: 'text/csv',
                status: 'skipped',
                reason: 'empty_text',
              },
            ],
          },
        })}
      />,
    );

    const summary = screen.getByTestId('message-attachment-status-summary');
    expect(summary).toHaveTextContent('1');
    expect(summary).toHaveTextContent('1,234');
    expect(screen.getByTestId('attachment-status-ok')).toBeInTheDocument();
    expect(screen.getByTestId('attachment-status-skipped')).toBeInTheDocument();
  });

  it('shows failed status for error entries', () => {
    renderWithI18n(
      <Message
        message={makeUserMsg({
          client_meta: {
            attachments: [{ name: 'broken.docx', size: 64, type: 'application/msword' }],
            attachments_status: [
              {
                media_id: 'm3',
                filename: 'broken.docx',
                mime_type: 'application/msword',
                status: 'error',
                reason: 'extract_failed:ValueError',
              },
            ],
          },
        })}
      />,
    );
    expect(screen.getByTestId('attachment-status-error')).toBeInTheDocument();
  });

  it('opens the PDF preview when a PDF attachment chip is clicked', async () => {
    renderWithI18n(
      <Message
        message={makeUserMsg({
          client_meta: {
            attachments: [{ name: 'paper.pdf', size: 100, type: 'application/pdf' }],
            attachments_status: [
              {
                media_id: 'pdf1',
                filename: 'paper.pdf',
                mime_type: 'application/pdf',
                status: 'ok',
                pages: 20,
                figures: 3,
              },
            ],
          },
        })}
      />,
    );
    const chip = screen.getByTestId('message-attachment-ref');
    expect(chip).toHaveAttribute('title', expect.stringContaining('20 页 · 3 图'));
    fireEvent.click(chip);
    const iframe = await screen.findByTestId('media-pdf-iframe');
    expect(iframe).toHaveAttribute('src', 'blob:pdf-1');
  });
});
