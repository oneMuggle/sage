import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import {
  BrandLogo,
  formatBrandLogoAuditJson,
  formatBrandLogoAuditSnapshot,
} from '../BrandLogo';

// Mock i18n: 把 sidebar.brand 与 brand.alt 直接当 fallback 行为。
// BrandLogo 内部调用 useI18n()；用 stub 提供确定的 t。
vi.mock('../../lib/i18n', () => ({
  useI18n: () => ({
    t: (key: string) => {
      const dict: Record<string, string> = {
        'brand.alt': 'Sage 标志',
        'sidebar.brand': 'Sage',
      };
      return dict[key] ?? key;
    },
    locale: 'zh',
  }),
}));

describe('BrandLogo', () => {
  it('renders an img pointing to ./sage.svg with default alt', () => {
    render(<BrandLogo />);
    const img = screen.getByRole('img', { name: 'Sage 标志' });
    expect(img).toBeInTheDocument();
    expect(img).toHaveAttribute('src', './sage.svg');
  });

  it('passes custom testId through to the img (Welcome reuse)', () => {
    render(<BrandLogo size="xl" testId="welcome-avatar" />);
    expect(screen.getByTestId('welcome-avatar')).toBeInTheDocument();
  });

  it('honors custom alt override', () => {
    render(<BrandLogo alt="自定义 alt" />);
    expect(screen.getByAltText('自定义 alt')).toBeInTheDocument();
  });

  it('applies size class to the img', () => {
    const { rerender } = render(<BrandLogo size="xs" />);
    expect(screen.getByRole('img')).toHaveClass('w-4 h-4');

    rerender(<BrandLogo size="sm" />);
    expect(screen.getByRole('img')).toHaveClass('w-6 h-6');

    rerender(<BrandLogo size="xl" />);
    expect(screen.getByRole('img')).toHaveClass('w-16 h-16');
  });

  it('does NOT render wordmark by default', () => {
    render(<BrandLogo />);
    expect(screen.queryByText('Sage')).not.toBeInTheDocument();
  });

  it('renders wordmark when withWordmark is true', () => {
    render(<BrandLogo size="sm" withWordmark />);
    // img + wordmark 都在
    expect(screen.getByRole('img')).toBeInTheDocument();
    expect(screen.getByText('Sage')).toBeInTheDocument();
  });

  it('merges custom className', () => {
    render(<BrandLogo className="ml-2" />);
    const img = screen.getByRole('img');
    expect(img).toHaveClass('ml-2');
  });

  it('formats audit snapshot and JSON and supports copy controls (Phase P102)', () => {
    expect(
      formatBrandLogoAuditSnapshot({
        size: 'lg',
        withWordmark: true,
        alt: 'Sage 标志',
        testId: 'welcome-avatar',
      }),
    ).toBe('brandLogo|size=lg|wordmark=1|alt=Sage 标志|testId=welcome-avatar');
    expect(formatBrandLogoAuditSnapshot({})).toBe(
      'brandLogo|size=md|wordmark=0|alt=none|testId=brand-logo',
    );
    expect(
      JSON.parse(
        formatBrandLogoAuditJson({
          size: 'sm',
          withWordmark: false,
          alt: 'Sage',
          testId: 'brand-logo',
        }),
      ),
    ).toEqual({
      size: 'sm',
      withWordmark: false,
      alt: 'Sage',
      testId: 'brand-logo',
    });

    render(<BrandLogo />);
    const snapBtn = screen.getByTestId('brand-logo-copy-snapshot');
    const jsonBtn = screen.getByTestId('brand-logo-copy-json');
    fireEvent.click(snapBtn);
    expect(snapBtn).toHaveTextContent('已复制快照');
    fireEvent.click(jsonBtn);
    expect(jsonBtn).toHaveTextContent('已复制JSON');
  });
});
