// src/widgets/chat/preview/__tests__/FilePreviewPanel.test.tsx
// 消息内文件预览面板测试 — workspaceApi 全 mock，Shiki 同步化（jsdom 确定性）。
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { WorkspacePreviewContent } from '../../../../shared/api/workspaceApi';
import { FilePreviewPanel } from '../FilePreviewPanel';

const mockPreviewFile =
  vi.fn<(sessionId: string, path: string) => Promise<WorkspacePreviewContent>>();

vi.mock('../../../../shared/api/workspaceApi', () => ({
  workspaceApi: {
    previewFile: (sessionId: string, path: string) => mockPreviewFile(sessionId, path),
  },
}));

// Shiki 异步高亮在 jsdom 下不确定，mock 成同步 pre 保持断言确定
vi.mock('../../ShikiCodeBlock', () => ({
  ShikiCodeBlock: ({ children }: { children: string }) => (
    <pre data-testid="shiki-block">{children}</pre>
  ),
}));

beforeEach(() => {
  mockPreviewFile.mockReset();
});

function renderPanel(path = 'src/app.py') {
  return render(<FilePreviewPanel sessionId="s1" path={path} onBack={() => {}} />);
}

describe('FilePreviewPanel', () => {
  it('按路径加载并渲染代码内容', async () => {
    mockPreviewFile.mockResolvedValue({
      ok: true,
      kind: 'code',
      content: "print('hi')\n",
      truncated: false,
    });
    renderPanel();

    await waitFor(() => expect(mockPreviewFile).toHaveBeenCalledWith('s1', 'src/app.py'));
    expect(await screen.findByTestId('shiki-block')).toHaveTextContent("print('hi')");
    expect(screen.getByText('app.py')).toBeInTheDocument();
  });

  it('请求失败时显示错误信息', async () => {
    mockPreviewFile.mockRejectedValue(new Error('文件不存在'));
    renderPanel();

    expect(await screen.findByTestId('file-preview-error')).toHaveTextContent('文件不存在');
  });

  it('后端 ok=false 时显示后端错误', async () => {
    mockPreviewFile.mockResolvedValue({ ok: false, error: '二进制文件不支持预览' });
    renderPanel();

    expect(await screen.findByText('二进制文件不支持预览')).toBeInTheDocument();
  });

  it('内容截断时显示提示', async () => {
    mockPreviewFile.mockResolvedValue({
      ok: true,
      kind: 'text',
      content: 'x',
      truncated: true,
    });
    renderPanel('notes/big.txt');

    expect(await screen.findByText('内容过长，已截断显示')).toBeInTheDocument();
  });
});
