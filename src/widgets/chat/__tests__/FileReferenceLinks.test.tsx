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

  // ---------- URL 编码修复（2026-11-03）----------
  // mdast-util-to-hast 的 normalizeUri 把中文做了 percent-encoding，
  // 点击回调必须传解码后的原始路径，否则后端 404。

  it('中文路径 markdown 链接 → 点击后右栏拿到解码路径（非 percent-encoded）', () => {
    // react-markdown 管线中 normalizeUri 会把 "算法.md" → "%E7%AE%97%E6%B3%95.md"
    // 模拟 LLM 输出含中文文件路径的 markdown
    render(<MarkdownChunk md={'已生成 [算法](output/算法.md)'} />);

    const link = screen.getByTestId('markdown-file-link');
    expect(link).toBeInTheDocument();

    fireEvent.click(link);

    const state = useRightPanelStore.getState();
    // 关键断言：路径必须是解码后的中文，不能是 %E7%AE%97 之类的编码
    expect(state.selectedFilePath).toBe('output/算法.md');
    expect(state.selectedFilePath).not.toContain('%');
  });

  it('已编码的 href 也能被识别为本地文件路径', () => {
    // normalizeUri 编码后的路径仍应被 isLocalFilePathHref 判定为文件链接
    render(<MarkdownChunk md={'[文件](src/%E6%B5%8B%E8%AF%95/app.ts)'} />);
    expect(screen.getByTestId('markdown-file-link')).toBeInTheDocument();
  });
});
