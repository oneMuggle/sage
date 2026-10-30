import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { MarkdownImage } from '../MarkdownImage';

function renderImage(ui: React.ReactElement) {
  return render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);
}

describe('MarkdownImage — context menu', () => {
  it('opens the lightbox from the context menu', async () => {
    renderImage(<MarkdownImage src="https://example.com/a.png" alt="示例" />);
    const img = screen.getByTestId('markdown-image');
    fireEvent.load(img);

    fireEvent.contextMenu(img, { clientX: 5, clientY: 5 });
    fireEvent.click(await screen.findByRole('menuitem', { name: '查看大图' }));

    expect(screen.getByTestId('lightbox')).toBeInTheDocument();
  });

  it('disables the view action while the image is still loading', async () => {
    renderImage(<MarkdownImage src="https://example.com/b.png" alt="示例" />);
    const img = screen.getByTestId('markdown-image');

    fireEvent.contextMenu(img, { clientX: 5, clientY: 5 });
    fireEvent.click(await screen.findByRole('menuitem', { name: '查看大图' }));

    expect(screen.queryByTestId('lightbox')).toBeNull();
  });
});
