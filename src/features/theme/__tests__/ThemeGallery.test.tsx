import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ThemeGallery } from '../ThemeGallery';

const mockSetPresetId = vi.fn();

vi.mock('../../../app/providers/useTheme', () => ({
  useTheme: () => ({
    presetId: 'indigo',
    setPresetId: mockSetPresetId,
    resolved: 'light',
  }),
}));

vi.mock('../../../shared/lib/i18n', () => ({
  useI18n: () => ({
    t: (key: string) => {
      const translations: Record<string, string> = {
        'theme.gallery.section_basic': '基础主题',
        'theme.gallery.section_decorative': '装饰主题',
      };
      return translations[key] ?? key;
    },
  }),
}));

describe('ThemeGallery', () => {
  beforeEach(() => {
    mockSetPresetId.mockClear();
  });

  it('渲染基础主题区域标题', () => {
    render(<ThemeGallery />);
    expect(screen.getByText('基础主题')).toBeDefined();
  });

  it('渲染装饰主题区域标题', () => {
    render(<ThemeGallery />);
    expect(screen.getByText('装饰主题')).toBeDefined();
  });

  it('显示 6 套基础主题卡片', () => {
    render(<ThemeGallery />);
    expect(screen.getAllByRole('button')).toHaveLength(11);
  });

  it('基础主题卡片显示名称和描述', () => {
    render(<ThemeGallery />);
    expect(screen.getByText('Indigo')).toBeDefined();
    expect(screen.getByText('经典靛蓝，默认主题')).toBeDefined();
    expect(screen.getByText('Sage Green')).toBeDefined();
  });

  it('装饰主题卡片显示封面图', () => {
    render(<ThemeGallery />);
    const mintBlueImg = screen.getByAltText('Mint Blue');
    expect(mintBlueImg).toBeDefined();
    expect(mintBlueImg.getAttribute('src')).toBe('/themes/covers/mint-blue.svg');
  });

  it('点击基础主题卡片切换主题', () => {
    render(<ThemeGallery />);
    const sageGreenBtn = screen.getByText('Sage Green').closest('button');
    fireEvent.click(sageGreenBtn!);
    expect(mockSetPresetId).toHaveBeenCalledWith('sage-green');
  });

  it('点击装饰主题卡片切换主题', () => {
    render(<ThemeGallery />);
    const sakuraBtn = screen.getByText('Sakura').closest('button');
    fireEvent.click(sakuraBtn!);
    expect(mockSetPresetId).toHaveBeenCalledWith('sakura');
  });

  it('当前激活的主题有高亮样式', () => {
    render(<ThemeGallery />);
    const indigoBtn = screen.getByText('Indigo').closest('button');
    expect(indigoBtn?.className).toContain('border-primary');
  });

  it('非激活主题无高亮样式', () => {
    render(<ThemeGallery />);
    const sageBtn = screen.getByText('Sage Green').closest('button');
    expect(sageBtn?.className).not.toContain('border-primary');
  });
});
