/**
 * P3 (UI 优化方案 2026-09-13 循环二): 用户消息 URL 自动链接化。
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import type { Message as MessageType } from '../../../shared/lib/store';
import { Message } from '../Message';

const base: MessageType = {
  id: 'm1',
  session_id: 's1',
  role: 'user',
  content: '',
  created_at: 1,
};

describe('Message user link rendering (P3)', () => {
  it('用户消息中的 URL 渲染为可点链接', () => {
    render(
      <I18nProvider>
        <Message message={{ ...base, content: '看看 https://example.com/docs?a=1 这个页面' }} />
      </I18nProvider>,
    );
    const link = screen.getByRole('link', { name: /example\.com\/docs/ });
    expect(link).toHaveAttribute('href', 'https://example.com/docs?a=1');
    expect(link).toHaveAttribute('target', '_blank');
  });

  it('无 URL 的用户消息不渲染链接', () => {
    render(
      <I18nProvider>
        <Message message={{ ...base, content: '普通问题，没有链接' }} />
      </I18nProvider>,
    );
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });
});
