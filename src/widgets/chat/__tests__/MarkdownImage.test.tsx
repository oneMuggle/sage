/**
 * P1 (UI 优化方案 2026-09-13): markdown 图片渲染 — 骨架/渐入/失败占位/Lightbox。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import {
  MarkdownImage,
  formatMarkdownImageAuditJson,
  formatMarkdownImageAuditSnapshot,
} from '../MarkdownImage';

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

  it('formats audit snapshot and JSON and supports copy controls (Phase P101)', () => {
    expect(
      formatMarkdownImageAuditSnapshot({
        src: 'https://example.com/a.png',
        alt: 'demo',
        status: 'loaded',
        isLocalMedia: false,
        lightboxOpen: true,
      }),
    ).toBe(
      'markdownImage|src=https://example.com/a.png|alt=demo|status=loaded|local=0|lightbox=1',
    );
    expect(formatMarkdownImageAuditSnapshot({})).toBe(
      'markdownImage|src=none|alt=none|status=loading|local=0|lightbox=0',
    );
    expect(
      JSON.parse(
        formatMarkdownImageAuditJson({
          src: '/api/v1/media/123',
          alt: 'local',
          status: 'loading',
          isLocalMedia: true,
          lightboxOpen: false,
        }),
      ),
    ).toEqual({
      src: '/api/v1/media/123',
      alt: 'local',
      status: 'loading',
      isLocalMedia: true,
      lightboxOpen: false,
    });

    render(<MarkdownImage src="https://example.com/a.png" alt="示例" />);
    const snapBtn = screen.getByTestId('markdown-image-copy-snapshot');
    const jsonBtn = screen.getByTestId('markdown-image-copy-json');
    fireEvent.click(snapBtn);
    expect(snapBtn).toHaveTextContent('已复制快照');
    fireEvent.click(jsonBtn);
    expect(jsonBtn).toHaveTextContent('已复制JSON');
  });
});
