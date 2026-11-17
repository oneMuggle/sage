/**
 * 2026-11-15 回归：拖入文件到会话输入框后，"拖放文件到此处"遮罩必须
 * 随 drop 或取消拖拽消失，且输入区域保持可交互。
 *
 * 缺陷现场：卡内覆盖层（旧 InputCard 实现）盖住 textarea，drop 目标落在
 * 覆盖层上被全局 hook 判为"卡外"，捕获阶段 stopPropagation 后 composer
 * 的 React onDrop 永不执行 → isDragOver 无人复位 → 遮罩卡死、无法输入。
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { useGlobalFileDrop } from '../../../shared/lib/hooks/useGlobalFileDrop';
import { I18nProvider } from '../../../shared/lib/i18n';
import { ChatInput } from '../ChatInput';

function Harness() {
  const { isDragOver } = useGlobalFileDrop();
  return (
    <div>
      {isDragOver && (
        // 与 Chat.tsx 同款：pointer-events-none 保证遮罩不阻断输入。
        <div data-testid="global-drop-overlay" className="pointer-events-none" />
      )}
      <ChatInput onSend={vi.fn()} />
    </div>
  );
}

const renderHarness = () =>
  render(
    <I18nProvider defaultLocale="zh">
      <Harness />
    </I18nProvider>,
  );

function fileDragEvent(file: File) {
  return { dataTransfer: { types: ['Files'], files: [file] } };
}

describe('ChatInput — 全局拖放回归', () => {
  it('drop 落在输入卡容器（非 textarea）→ 遮罩消失且附件入列', async () => {
    renderHarness();
    const file = new File(['hello'], 'a.md', { type: 'text/markdown' });
    const textarea = screen.getByTestId('chat-input');
    act(() => {
      fireEvent.dragEnter(document.body, fileDragEvent(file));
    });
    expect(screen.getByTestId('global-drop-overlay')).toBeTruthy();
    act(() => {
      // 输入卡容器 = textarea 的祖先区域，之前会被误判为"卡外"的路径。
      fireEvent.drop(textarea.parentElement as HTMLElement, fileDragEvent(file));
    });
    expect(screen.queryByTestId('global-drop-overlay')).toBeNull();
    await waitFor(() => expect(screen.getByText('a.md')).toBeTruthy());
  });

  it('drop 落在 textarea 本身 → 遮罩消失且附件入列', async () => {
    renderHarness();
    const file = new File(['hello'], 'b.txt', { type: 'text/plain' });
    act(() => {
      fireEvent.dragEnter(document.body, fileDragEvent(file));
    });
    act(() => {
      fireEvent.drop(screen.getByTestId('chat-input'), fileDragEvent(file));
    });
    expect(screen.queryByTestId('global-drop-overlay')).toBeNull();
    await waitFor(() => expect(screen.getByText('b.txt')).toBeTruthy());
  });

  it('取消拖拽（dragend，未 drop）→ 遮罩消失，输入框可聚焦', () => {
    renderHarness();
    act(() => {
      fireEvent.dragEnter(document.body, fileDragEvent(new File(['x'], 'c.txt')));
    });
    expect(screen.getByTestId('global-drop-overlay')).toBeTruthy();
    act(() => {
      fireEvent.dragEnd(document.body);
    });
    expect(screen.queryByTestId('global-drop-overlay')).toBeNull();
    const textarea = screen.getByTestId('chat-input') as HTMLTextAreaElement;
    textarea.focus();
    expect(document.activeElement).toBe(textarea);
  });

  it('整页遮罩带 pointer-events-none（不阻断输入）', () => {
    renderHarness();
    act(() => {
      fireEvent.dragEnter(document.body, fileDragEvent(new File(['x'], 'd.txt')));
    });
    expect(screen.getByTestId('global-drop-overlay').className).toContain('pointer-events-none');
  });
});
