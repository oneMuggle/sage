import { render, screen } from '@testing-library/react';
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

describe('Message · PlanningTimeline', () => {
  beforeEach(() => {
    useChatStreamStore.setState({ sessions: {} });
  });

  it('assistant 气泡渲染规划时间线', () => {
    useChatStreamStore.getState().setPlanProgress('s1', {
      stage: 'mode_classify',
      status: 'started',
      kind: 'message',
      text: '',
    });
    render(
      <I18nProvider defaultLocale="zh">
        <Message message={base} />
      </I18nProvider>,
    );
    expect(screen.getByTestId('planning-timeline')).toBeInTheDocument();
  });
});
