/**
 * P1 (UI 优化方案 2026-09-13): 统一 Lightbox 行为 — ESC/关闭按钮/工具栏。
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { Lightbox } from '../Lightbox/Lightbox';

describe('Lightbox', () => {
  it('portal 渲染图片与缩放指示', () => {
    render(<Lightbox src="blob:http://x/img" alt="测试图" onClose={vi.fn()} />);
    expect(screen.getByTestId('lightbox')).toBeInTheDocument();
    expect(screen.getByTestId('lightbox-image')).toHaveAttribute('src', 'blob:http://x/img');
    expect(screen.getByTestId('lightbox-zoom')).toHaveTextContent('100%');
  });

  it('ESC 关闭', () => {
    const onClose = vi.fn();
    render(<Lightbox src="x.png" onClose={onClose} />);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('关闭按钮与点背景关闭', () => {
    const onClose = vi.fn();
    render(<Lightbox src="x.png" onClose={onClose} />);
    fireEvent.click(screen.getByLabelText('关闭'));
    expect(onClose).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByTestId('lightbox'));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it('放大/重置按钮更新缩放显示', () => {
    render(<Lightbox src="x.png" onClose={vi.fn()} />);
    fireEvent.click(screen.getByLabelText('放大'));
    expect(screen.getByTestId('lightbox-zoom')).toHaveTextContent('115%');
    fireEvent.click(screen.getByLabelText('重置'));
    expect(screen.getByTestId('lightbox-zoom')).toHaveTextContent('100%');
  });
});
