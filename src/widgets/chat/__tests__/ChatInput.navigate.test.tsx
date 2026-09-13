/**
 * 对标 S3: 页面直达 slash 命令（/office /journal /schedule /wiki /memory）
 * 选中即跳转，不发消息。
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { ChatInput } from '../ChatInput';

vi.mock('../../../shared/lib/hooks/useFileUpload', () => ({
  useFileUpload: () => ({
    files: [],
    images: [],
    addFile: vi.fn(),
    addImage: vi.fn(),
    removeFile: vi.fn(),
    removeImage: vi.fn(),
    clearAll: vi.fn(),
    handleDrop: vi.fn(),
    handleDragOver: vi.fn(),
    isDragOver: false,
  }),
}));

function LocationProbe() {
  const loc = useLocation();
  return <div data-testid="loc">{loc.pathname}</div>;
}

function renderAtChat(onSend: () => void) {
  return render(
    <I18nProvider defaultLocale="zh">
      <MemoryRouter initialEntries={['/chat']}>
        <LocationProbe />
        <Routes>
          <Route path="*" element={<ChatInput onSend={onSend} />} />
        </Routes>
      </MemoryRouter>
    </I18nProvider>,
  );
}

describe('ChatInput — navigate slash commands (S3)', () => {
  it('navigates to /office on /office without sending', () => {
    const onSend = vi.fn();
    renderAtChat(onSend);
    const input = screen.getByPlaceholderText(/输入消息/);
    fireEvent.change(input, { target: { value: '/office' } });
    fireEvent.mouseDown(screen.getByRole('button', { name: /\/office/ }));
    expect(screen.getByTestId('loc').textContent).toBe('/office');
    expect(onSend).not.toHaveBeenCalled();
    expect((input as HTMLTextAreaElement).value).toBe('');
  });

  it('navigates to /scheduled on /schedule', () => {
    const onSend = vi.fn();
    renderAtChat(onSend);
    const input = screen.getByPlaceholderText(/输入消息/);
    fireEvent.change(input, { target: { value: '/schedule' } });
    fireEvent.mouseDown(screen.getByRole('button', { name: /\/schedule/ }));
    expect(screen.getByTestId('loc').textContent).toBe('/scheduled');
    expect(onSend).not.toHaveBeenCalled();
  });
});
