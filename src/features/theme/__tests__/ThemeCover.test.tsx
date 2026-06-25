import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ThemeCover } from '../ThemeCover';

describe('ThemeCover', () => {
  it('渲染封面图', () => {
    render(<ThemeCover src="/covers/test.svg" alt="test" />);
    const img = screen.getByRole('img', { name: 'test' });
    expect(img).toBeDefined();
    expect(img.getAttribute('src')).toBe('/covers/test.svg');
  });

  it('加载失败时显示渐变色降级', () => {
    render(
      <ThemeCover src="/covers/broken.svg" alt="broken" gradientFrom="#ff0000" gradientTo="#0000ff" />,
    );
    const img = screen.getByRole('img');
    fireEvent.error(img);
    const fallback = screen.getByTestId('theme-cover-fallback');
    expect(fallback).toBeDefined();
    const style = fallback.getAttribute('style') ?? '';
    expect(style).toContain('linear-gradient');
    // jsdom converts hex to rgb: #ff0000 → rgb(255, 0, 0), #0000ff → rgb(0, 0, 255)
    expect(style).toContain('255, 0, 0');
    expect(style).toContain('0, 0, 255');
  });

  it('未提供渐变色时使用默认灰度', () => {
    render(<ThemeCover src="/broken.svg" alt="fallback" />);
    const img = screen.getByRole('img');
    fireEvent.error(img);
    const fallback = screen.getByTestId('theme-cover-fallback');
    const style = fallback.getAttribute('style') ?? '';
    expect(style).toContain('linear-gradient');
    // jsdom converts hex to rgb: #6b7280 → rgb(107, 114, 128)
    expect(style).toContain('107, 114, 128');
    expect(style).toContain('55, 65, 81');
  });
});
