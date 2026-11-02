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

const message: Message = {
  id: 'm-ocr',
  session_id: 's-1',
  role: 'user',
  content: '看图',
  created_at: 1_750_000_000_000,
  client_meta: {
    image_ocr_texts: [{ name: 'shot.png', text: '截图里的文字' }],
  },
};

describe('MessageClientMeta — image OCR text', () => {
  it('renders and copies the stored OCR text', () => {
    render(
      <I18nProvider defaultLocale="zh">
        <MessageClientMeta message={message} isUser />
      </I18nProvider>,
    );

    expect(screen.getByTestId('message-image-ocr')).toBeInTheDocument();
    expect(screen.getByText('截图里的文字')).toBeInTheDocument();
    fireEvent.click(screen.getByText('复制文字'));
    expect(mocks.copyToClipboard).toHaveBeenCalledWith(
      '截图里的文字',
      expect.any(Object),
    );
  });
});
