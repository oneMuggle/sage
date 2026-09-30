/**
 * UX-IA R1 批次 D：会话控件（模型 / 上下文 / 权限）移入输入框右下角。
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { InputCard } from '../InputCard';

vi.mock('../../../shared/lib/i18n', () => ({
  useI18n: () => ({ t: (key: string) => key, locale: 'zh' }),
}));

const base = { value: '', onChange: vi.fn(), onSubmit: vi.fn() };

describe('InputCard composerControls slot', () => {
  it('renders nothing extra when no controls are passed', () => {
    render(<InputCard {...base} />);
    expect(screen.queryByTestId('composer-controls')).toBeNull();
  });

  it('renders controls before the send button', () => {
    render(<InputCard {...base} composerControls={<span data-testid="model-picker">m</span>} />);
    const slot = screen.getByTestId('composer-controls');
    expect(slot).toContainElement(screen.getByTestId('model-picker'));
    const send = screen.getByTestId('chat-send');
    expect(slot.compareDocumentPosition(send) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('keeps controls visible while a response is streaming', () => {
    render(
      <InputCard {...base} isLoading onInterrupt={vi.fn()} composerControls={<span>ctl</span>} />,
    );
    expect(screen.getByTestId('composer-controls')).toHaveTextContent('ctl');
    expect(screen.queryByTestId('chat-send')).toBeNull();
  });
});
