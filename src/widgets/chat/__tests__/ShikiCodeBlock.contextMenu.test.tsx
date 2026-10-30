import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { ShikiCodeBlock } from '../ShikiCodeBlock';

const mocks = vi.hoisted(() => ({
  copyToClipboard: vi.fn(() => Promise.resolve(true)),
}));

vi.mock('../../../shared/lib/clipboard', () => ({
  copyToClipboard: mocks.copyToClipboard,
}));

function renderBlock(language: string, code: string) {
  return render(
    <I18nProvider defaultLocale="zh">
      <ShikiCodeBlock language={language}>{code}</ShikiCodeBlock>
    </I18nProvider>,
  );
}

describe('ShikiCodeBlock — context menu', () => {
  it('copies the raw code from the context menu', async () => {
    renderBlock('ts', 'const a = 1;');

    fireEvent.contextMenu(screen.getByTestId('code-block-header'), { clientX: 5, clientY: 5 });
    fireEvent.click(await screen.findByRole('menuitem', { name: '复制代码' }));

    expect(mocks.copyToClipboard).toHaveBeenCalledWith('const a = 1;', expect.any(Object));
  });

  it('copies a markdown fence preserving the language tag', async () => {
    renderBlock('ts', 'const a = 1;\n');

    fireEvent.contextMenu(screen.getByTestId('code-block-header'), { clientX: 5, clientY: 5 });
    fireEvent.click(await screen.findByRole('menuitem', { name: '复制为 Markdown 围栏' }));

    expect(mocks.copyToClipboard).toHaveBeenCalledWith(
      '```ts\nconst a = 1;\n```',
      expect.any(Object),
    );
  });
});
