/**
 * P1 (UI 优化方案 2026-09-13): markdown 图片渲染 — 骨架/渐入/失败占位/Lightbox。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { MarkdownImage } from '../MarkdownImage';

describe('MarkdownImage', () => {
  it('加载中显示骨架，onLoad 后渐入', async () => {
    render(<MarkdownImage src="https://example.com/a.png" alt="示例" />);
    expect(screen.getByTestId('markdown-image-skeleton')).toBeInTheDocument();

    fireEvent.load(screen.getByTestId('markdown-image'));
    await waitFor(() => {
      expect(screen.queryByTestId('markdown-image-skeleton')).not.toBeInTheDocument();
    });
  });

  it('加载失败显示失败占位', () => {
    render(<MarkdownImage src="https://example.com/broken.png" />);
    fireEvent.error(screen.getByTestId('markdown-image'));
    expect(screen.getByTestId('markdown-image-error')).toBeInTheDocument();
  });

  it('点击图片打开 Lightbox', () => {
    render(<MarkdownImage src="https://example.com/a.png" />);
    const img = screen.getByTestId('markdown-image');
    fireEvent.load(img);
    fireEvent.click(img);
    expect(screen.getByTestId('lightbox')).toBeInTheDocument();
  });

  it('src 缺失时不渲染', () => {
    const { container } = render(<MarkdownImage />);
    expect(container).toBeEmptyDOMElement();
  });
});
