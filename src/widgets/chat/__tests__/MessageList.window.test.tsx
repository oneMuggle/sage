// src/widgets/chat/__tests__/MessageList.window.test.tsx
// U11 (批次 C-3): 长会话尾窗渲染 + 加载更早。
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

import type { Message as MessageType } from '../../../shared/lib/store';
import { MessageList } from '../MessageList';

vi.mock('../Message', () => ({
  Message: ({ message }: { message: { id: string; content: string } }) => (
    <div data-testid={`msg-${message.id}`}>{message.content}</div>
  ),
}));

vi.mock('../../../features/chat', () => ({
  BtwOverlay: () => null,
}));

function makeMessages(n: number): MessageType[] {
  return Array.from({ length: n }, (_, i) => ({
    id: `m${i + 1}`,
    session_id: 's1',
    role: i % 2 === 0 ? ('user' as const) : ('assistant' as const),
    content: `内容 ${i + 1}`,
    created_at: i,
  }));
}

describe('MessageList windowing (U11)', () => {
  it('renders short sessions fully', () => {
    render(<MessageList messages={makeMessages(10)} />);
    expect(screen.getByTestId('msg-m1')).toBeInTheDocument();
    expect(screen.getByTestId('msg-m10')).toBeInTheDocument();
    expect(screen.queryByTestId('load-earlier')).toBeNull();
  });

  it('windows long sessions to the last 60 with a load-earlier control', () => {
    render(<MessageList messages={makeMessages(150)} />);
    // 最早的被窗口裁掉
    expect(screen.queryByTestId('msg-m1')).toBeNull();
    // 最近 60 条可见
    expect(screen.getByTestId('msg-m150')).toBeInTheDocument();
    expect(screen.getByTestId('msg-m91')).toBeInTheDocument();
    expect(screen.queryByTestId('msg-m90')).toBeNull();
    expect(screen.getByTestId('load-earlier')).toHaveTextContent(/还有 90 条/);
  });

  it('loads earlier messages on click', () => {
    render(<MessageList messages={makeMessages(150)} />);
    fireEvent.click(screen.getByTestId('load-earlier'));
    // 60 + 60 = 120 可见 → m31 成为最早可见
    expect(screen.getByTestId('msg-m31')).toBeInTheDocument();
    expect(screen.queryByTestId('msg-m30')).toBeNull();
    expect(screen.getByTestId('load-earlier')).toHaveTextContent(/还有 30 条/);
  });

  it('resets window when session changes', () => {
    const { rerender } = render(<MessageList messages={makeMessages(150)} />);
    fireEvent.click(screen.getByTestId('load-earlier'));
    expect(screen.getByTestId('msg-m31')).toBeInTheDocument();

    const other = makeMessages(150).map((m) => ({
      ...m,
      id: `x${m.id}`,
      session_id: 's2',
    }));
    rerender(<MessageList messages={other} />);
    // 窗口重置: 只见最近 60 条
    expect(screen.queryByTestId('msg-xm31')).toBeNull();
    expect(screen.getByTestId('msg-xm150')).toBeInTheDocument();
  });
});
