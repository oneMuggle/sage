// 对话阅读体验第二轮：Message 接线 —— C1 生成速度统计、C2 回答版本切换器。
import { act, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import type { Message as MessageType } from '../../../shared/lib/store';
import { Message } from '../Message';

vi.mock('../../../features/chat/answerVersions', () => ({
  fetchAnswerVersions: vi.fn().mockResolvedValue({
    anchor_id: 'u1',
    total: 2,
    current_index: 2,
    versions: [
      { id: 'ver-1', generated_at: 1, preview: '旧', current: false },
      { id: 'current', generated_at: 2, preview: '新', current: true },
    ],
  }),
  activateAnswerVersion: vi.fn(),
}));

const assistant = (patch: Partial<MessageType> = {}): MessageType => ({
  id: 'a-1',
  session_id: 's-1',
  role: 'assistant',
  content: '回答正文。',
  created_at: 1_750_000_000_000,
  ...patch,
});

const withI18n = (ui: React.ReactElement) => <I18nProvider defaultLocale="zh">{ui}</I18nProvider>;

describe('Message — generation stats (C1)', () => {
  it('shows the stats on finished assistant replies only', () => {
    const stats = { output_tokens: 20, latency_ms: 2000 };
    const { rerender } = render(
      withI18n(<Message message={assistant({ generation_stats: stats })} />),
    );
    expect(screen.getByTestId('generation-stats')).toHaveTextContent('10.0 tok/s');

    rerender(withI18n(<Message message={assistant({ generation_stats: stats })} isStreaming />));
    expect(screen.queryByTestId('generation-stats')).toBeNull();

    rerender(withI18n(<Message message={assistant({ role: 'user', generation_stats: stats })} />));
    expect(screen.queryByTestId('generation-stats')).toBeNull();
  });
});

describe('Message — answer versions (C2)', () => {
  it('renders the switcher only when the list hands over the callback', async () => {
    const { rerender } = render(
      withI18n(<Message message={assistant()} onAnswerVersionChange={vi.fn()} />),
    );
    expect(await screen.findByTestId('answer-version-count')).toHaveTextContent('2/2');

    rerender(withI18n(<Message message={assistant()} />));
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.queryByTestId('answer-version-switcher')).toBeNull();
  });
});
