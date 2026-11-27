import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { useChatStreamStore } from '../../../features/send-message/chatStreamStore';
import { I18nProvider } from '../../../shared/lib/i18n';
import type { Message as MessageType } from '../../../shared/lib/store';
import { Message } from '../Message';

const base: MessageType = {
  id: 'm1',
  session_id: 's1',
  role: 'assistant',
  content: '',
  created_at: 1,
};

describe('Message · FactReconBlock 集成', () => {
  beforeEach(() => {
    useChatStreamStore.setState({ sessions: {} });
  });

  it('assistant 气泡带 client_meta.scout_facts 时渲染事实侦察区块', () => {
    render(
      <I18nProvider defaultLocale="zh">
        <Message
          message={{
            ...base,
            client_meta: {
              scout_facts: {
                facts: [
                  { text: '落库事实甲的完整正文', source: '文档 A' },
                  { text: '落库事实乙的完整正文', source: '' },
                ],
                fact_count: 2,
                truncated: false,
              },
            },
          }}
        />
      </I18nProvider>,
    );
    expect(screen.getByTestId('fact-recon-block')).toBeInTheDocument();
    expect(screen.getByTestId('fact-recon-count')).toHaveTextContent('2 条事实');

    fireEvent.click(screen.getByTestId('fact-recon-toggle'));
    expect(screen.getByTestId('fact-recon-list').textContent).toContain('落库事实甲的完整正文');
  });

  it('assistant 气泡无 scout_facts 时不渲染事实侦察区块', () => {
    render(
      <I18nProvider defaultLocale="zh">
        <Message message={base} />
      </I18nProvider>,
    );
    expect(screen.queryByTestId('fact-recon-block')).not.toBeInTheDocument();
  });

  it('user 气泡不渲染事实侦察区块', () => {
    render(
      <I18nProvider defaultLocale="zh">
        <Message
          message={{
            ...base,
            role: 'user',
            client_meta: {
              scout_facts: {
                facts: [{ text: '不该出现', source: '' }],
                fact_count: 1,
              },
            },
          }}
        />
      </I18nProvider>,
    );
    expect(screen.queryByTestId('fact-recon-block')).not.toBeInTheDocument();
  });
});
