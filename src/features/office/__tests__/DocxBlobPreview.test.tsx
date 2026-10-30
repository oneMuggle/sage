// src/features/office/__tests__/DocxBlobPreview.test.tsx
//
// 2026-10-29: 聊天产物 Word 版式预览容器 —— 渲染失败/空输出必须通知父级
// 回退结构化视图，而不是留下空白板。

import { render, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../DocxNativePreview', () => ({
  renderDocxDataUrl: vi.fn(),
}));

import { DocxBlobPreview } from '../DocxBlobPreview';
import { renderDocxDataUrl } from '../DocxNativePreview';

const mockRender = vi.mocked(renderDocxDataUrl);

describe('DocxBlobPreview', () => {
  beforeEach(() => {
    mockRender.mockReset();
  });

  it('渲染成功后进入 ok 状态', async () => {
    mockRender.mockImplementation(async (container) => {
      container.innerHTML = '<p>正文</p>';
    });
    const { getByTestId } = render(<DocxBlobPreview dataUrl="data:docx;base64,xxx" />);
    await waitFor(() => {
      expect(getByTestId('docx-blob-preview')).toHaveAttribute('data-state', 'ok');
    });
  });

  it('渲染抛错时调用 onError（父级回退结构化视图）', async () => {
    mockRender.mockRejectedValue(new Error('corrupt docx'));
    const onError = vi.fn();
    render(<DocxBlobPreview dataUrl="data:docx;base64,bad" onError={onError} />);
    await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
  });

  it('渲染无任何节点时也调用 onError，避免空白板', async () => {
    mockRender.mockResolvedValue(undefined);
    const onError = vi.fn();
    render(<DocxBlobPreview dataUrl="data:docx;base64,empty" onError={onError} />);
    await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
  });
});
