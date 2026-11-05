/**
 * P2 (2026-11-04): ChatInput 订阅 `sage:composer-drop` CustomEvent，
 * 以便聊天页根容器的全局拖放能把文件分发到 useFileUpload 的 addFile/addImage。
 */
import { render, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { ChatInput } from '../ChatInput';

const addFileSpy = vi.fn();
const addImageSpy = vi.fn();

vi.mock('../../../shared/lib/hooks/useFileUpload', () => ({
  useFileUpload: () => ({
    files: [],
    images: [],
    addFile: addFileSpy,
    addImage: addImageSpy,
    removeFile: vi.fn(),
    removeImage: vi.fn(),
    clearAll: vi.fn(),
    handleDrop: vi.fn(),
    handleDragOver: vi.fn(),
    handlePaste: vi.fn(),
    isDragOver: false,
  }),
}));

const renderWithI18n = (ui: React.ReactElement) =>
  render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);

describe('ChatInput — sage:composer-drop listener', () => {
  beforeEach(() => {
    addFileSpy.mockClear();
    addImageSpy.mockClear();
  });

  it('把 CustomEvent 中的图片文件路由到 addImage', async () => {
    renderWithI18n(<ChatInput onSend={vi.fn()} />);
    const img = new File(['x'], 'p.png', { type: 'image/png' });
    window.dispatchEvent(new CustomEvent('sage:composer-drop', { detail: { files: [img] } }));
    await waitFor(() => expect(addImageSpy).toHaveBeenCalledWith(img));
  });

  it('把 CustomEvent 中的文档文件路由到 addFile', async () => {
    renderWithI18n(<ChatInput onSend={vi.fn()} />);
    const doc = new File(['x'], 'd.py', { type: 'text/plain' });
    window.dispatchEvent(new CustomEvent('sage:composer-drop', { detail: { files: [doc] } }));
    await waitFor(() => expect(addFileSpy).toHaveBeenCalledWith(doc));
  });

  it('忽略空 detail（不抛错）', () => {
    renderWithI18n(<ChatInput onSend={vi.fn()} />);
    expect(() => {
      window.dispatchEvent(new CustomEvent('sage:composer-drop', { detail: null }));
      window.dispatchEvent(new CustomEvent('sage:composer-drop', {}));
      window.dispatchEvent(new CustomEvent('sage:composer-drop', { detail: { files: [] } }));
    }).not.toThrow();
    expect(addFileSpy).not.toHaveBeenCalled();
    expect(addImageSpy).not.toHaveBeenCalled();
  });
});
