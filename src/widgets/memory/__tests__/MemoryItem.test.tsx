/**
 * MemoryItem 测试
 * - 渲染内容、类型标签、星级
 * - U12 两步式确认：第一次点击 armed，第二次点击触发 onDelete
 * - 单次点击（仅 armed）不调用 onDelete
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { Memory } from '../../../shared/api';
import { MemoryItem } from '../MemoryItem';

const baseMemory: Memory = {
  id: 'mem-1',
  content: '记住这件事',
  summary: '',
  memory_type: 'episodic',
  importance: 8,
  tags: ['工作', '重要'],
  created_at: Date.UTC(2026, 5, 1, 12, 0, 0),
  access_count: 0,
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe('MemoryItem', () => {
  it('renders content, type label, and tags', () => {
    render(<MemoryItem memory={baseMemory} onDelete={() => undefined} />);
    expect(screen.getByText('记住这件事')).toBeInTheDocument();
    expect(screen.getByText('情景')).toBeInTheDocument();
    expect(screen.getByText('工作')).toBeInTheDocument();
    expect(screen.getByText('重要')).toBeInTheDocument();
  });

  it('calls onDelete after two-step confirm (click twice, U12)', () => {
    const onDelete = vi.fn();
    render(<MemoryItem memory={baseMemory} onDelete={onDelete} />);
    fireEvent.click(screen.getByTitle('删除记忆')); // 第一次点击：armed
    expect(onDelete).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTitle('确认删除?')); // 第二次点击：确认
    expect(onDelete).toHaveBeenCalledWith('mem-1');
  });

  it('does not call onDelete on a single click (armed only, U12)', () => {
    const onDelete = vi.fn();
    render(<MemoryItem memory={baseMemory} onDelete={onDelete} />);
    fireEvent.click(screen.getByTitle('删除记忆'));
    expect(onDelete).not.toHaveBeenCalled();
  });
});
