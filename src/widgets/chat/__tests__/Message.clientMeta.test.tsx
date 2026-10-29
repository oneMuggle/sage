/**
 * 用户消息引用信息回显 —— 附件 / @ 文件引用 / office 引用 / 知识库引用。
 * client_meta 由后端 get_messages 回读，刷新会话后仍应渲染。
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import type { Message as MessageType } from '../../../shared/lib/store';
import { Message } from '../Message';

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
});
