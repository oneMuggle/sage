import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { ConverterGuideDialog } from '../canvas/ConverterGuideDialog';

describe('ConverterGuideDialog', () => {
  it('renders title and body when open', () => {
    render(
      <I18nProvider defaultLocale="zh">
        <ConverterGuideDialog open={true} onOpenChange={() => {}} />
      </I18nProvider>,
    );
    expect(screen.getByTestId('converter-guide-dialog')).toBeInTheDocument();
    expect(screen.getByText('导出 PDF 需要安装转换器')).toBeInTheDocument();
  });

  it('invokes onOpenChange(false) when the close button is clicked', () => {
    const onOpenChange = vi.fn();
    render(
      <I18nProvider defaultLocale="zh">
        <ConverterGuideDialog open={true} onOpenChange={onOpenChange} />
      </I18nProvider>,
    );
    fireEvent.click(screen.getByRole('button', { name: '关闭' }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('does not render when closed', () => {
    render(
      <I18nProvider defaultLocale="zh">
        <ConverterGuideDialog open={false} onOpenChange={() => {}} />
      </I18nProvider>,
    );
    expect(screen.queryByTestId('converter-guide-dialog')).not.toBeInTheDocument();
  });
});
