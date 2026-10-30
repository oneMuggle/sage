import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useRef } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import {
  markContextMenuOpen,
  resetContextMenuOpenCount,
} from '../../../shared/ui/ContextMenu/contextMenuEvents';
import { SelectionQuoteButton } from '../SelectionQuoteButton';

vi.mock('../../../features/chat/selectionQuote', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../features/chat/selectionQuote')>();
  return {
    ...actual,
    getQuotableSelection: vi.fn(() => ({ text: '选中的文本', rect: null })),
  };
});

function Harness() {
  const ref = useRef<HTMLDivElement>(null);
  return (
    <div ref={ref}>
      <SelectionQuoteButton rootRef={ref} onQuote={vi.fn()} />
    </div>
  );
}

function renderButton() {
  return render(
    <I18nProvider defaultLocale="zh">
      <Harness />
    </I18nProvider>,
  );
}

beforeEach(() => {
  // 组件用 RAF 延迟评估选区；测试里同步执行，避免 act() 之外的延迟 setState 告警
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
    cb(0);
    return 0;
  });
  vi.stubGlobal('cancelAnimationFrame', () => {});
});

afterEach(() => {
  resetContextMenuOpenCount();
  vi.unstubAllGlobals();
});

describe('SelectionQuoteButton — context menu mutual exclusion', () => {
  it('hides while a context menu is open and returns after it closes', async () => {
    renderButton();

    fireEvent.mouseUp(document);
    expect(await screen.findByTestId('selection-quote-button')).toBeInTheDocument();

    markContextMenuOpen(true);
    await waitFor(() => expect(screen.queryByTestId('selection-quote-button')).toBeNull());

    markContextMenuOpen(false);
    fireEvent.mouseUp(document);
    expect(await screen.findByTestId('selection-quote-button')).toBeInTheDocument();
  });
});
