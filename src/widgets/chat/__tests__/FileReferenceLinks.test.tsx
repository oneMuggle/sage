// src/widgets/chat/__tests__/FileReferenceLinks.test.tsx
// 消息内文件引用可点击（feat/file-reference-preview）：用户 @文件 chip、
// 工具卡文件名、markdown 文件链接 → 右栏文件预览；外链行为不变。
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { useRightPanelStore } from '../../../features/right-panel/rightPanelStore';
import { I18nProvider } from '../../../shared/lib/i18n';
import type { Message, ToolCall } from '../../../shared/lib/store';
import { MessageClientMeta } from '../MessageClientMeta';
import { MarkdownChunk } from '../MessageMarkdownParts';
import { FileWriteToolRenderer } from '../toolRenderers/FileWriteToolRenderer';

function resetStore() {
  useRightPanelStore.setState({
    open: false,
    selectedArtifactId: null,
    selectedFilePath: null,
  });
}

beforeEach(resetStore);

describe('MessageClientMeta — @文件 chip', () => {
  it('点击 chip 打开右栏文件预览', () => {
    const message = {
      id: 'm1',
      role: 'user',
      content: '看看 @src/App.tsx',
      client_meta: { file_refs: [{ path: 'src/App.tsx' }] },
    } as unknown as Message;

    render(
      <I18nProvider>
        <MessageClientMeta message={message} isUser />
      </I18nProvider>,
    );
    fireEvent.click(screen.getByTestId('message-file-ref'));

    const state = useRightPanelStore.getState();
    expect(state.open).toBe(true);
    expect(state.selectedFilePath).toBe('src/App.tsx');
  });
});

describe('FileWriteToolRenderer — 工具卡文件名', () => {
  it('点击文件名打开右栏文件预览', () => {
    const tc = {
      id: 'tc-write',
      name: 'write_file',
      args: { file_path: 'src/components/NewWidget.tsx' },
      result: 'ok',
    } as unknown as ToolCall;

    render(<FileWriteToolRenderer tc={tc} />);
    fireEvent.click(screen.getByTestId('file-write-path'));

    expect(useRightPanelStore.getState().selectedFilePath).toBe('src/components/NewWidget.tsx');
  });
});

describe('MarkdownChunk — 文件链接与外部链接', () => {
  it('本地文件链接拦截为右栏预览', () => {
    render(<MarkdownChunk md={'见 [报告](docs/report.md)'} />);
    fireEvent.click(screen.getByTestId('markdown-file-link'));

    expect(useRightPanelStore.getState().selectedFilePath).toBe('docs/report.md');
  });

  it('裸文件名（带扩展名）也识别为文件链接', () => {
    render(<MarkdownChunk md={'[报告](report.md)'} />);
    expect(screen.getByTestId('markdown-file-link')).toBeInTheDocument();
  });

  it('外部 http 链接保持原 a 标签行为', () => {
    render(<MarkdownChunk md={'[外链](https://example.com/page)'} />);

    const anchor = screen.getByText('外链').closest('a');
    expect(anchor).not.toBeNull();
    expect(anchor?.getAttribute('href')).toBe('https://example.com/page');
    expect(anchor?.getAttribute('target')).toBe('_blank');
  });
});
