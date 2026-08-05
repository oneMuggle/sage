// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import { MemoryCard } from '../MemoryCard';

const mockMemory = {
  id: 'm1',
  content: '用户偏好 KISS 风格',
  importance: 8,
  memory_type: 'episodic',
  memory_category: 'user_pref',
  session_id: 'abc-123',
  source_turn_id: 'turn-42',
  created_at: '2026-08-04T17:30:00Z',
};

function renderCard(memory: unknown, onDelete: (id: string) => void = () => {}) {
  return render(<MemoryCard memory={memory as never} onDelete={onDelete} />, {
    wrapper: MemoryRouter,
  });
}

describe('MemoryCard', () => {
  it('renders content and category label', () => {
    renderCard(mockMemory);
    expect(screen.getByText('用户偏好 KISS 风格')).toBeInTheDocument();
    // 分类中文标签（🧠 前缀区分于内容里的同名文本）
    expect(screen.getByText(/🧠 用户偏好/)).toBeInTheDocument();
  });

  it('shows traceability button when session_id and turn_id present', () => {
    renderCard(mockMemory);
    expect(screen.getByText(/Session/)).toBeInTheDocument();
  });

  it('calls onDelete when trash clicked', () => {
    const onDelete = vi.fn();
    renderCard(mockMemory, onDelete);
    fireEvent.click(screen.getByRole('button', { name: /删除/ }));
    expect(onDelete).toHaveBeenCalledWith('m1');
  });

  it('hides traceability when source_turn_id missing', () => {
    const m = { ...mockMemory, source_turn_id: undefined, source_message_id: undefined };
    renderCard(m);
    expect(screen.queryByText(/Session/)).not.toBeInTheDocument();
  });
});
