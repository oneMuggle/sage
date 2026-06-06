/**
 * MemoryItem 测试
 * - 渲染内容、类型标签、星级
 * - 点击删除按钮且 confirm 通过时触发 onDelete
 * - confirm 取消时不调用 onDelete
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { Memory } from '../../../lib/api';
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

  it('calls onDelete when confirm returns true', () => {
    const onDelete = vi.fn();
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<MemoryItem memory={baseMemory} onDelete={onDelete} />);
    fireEvent.click(screen.getByTitle('删除记忆'));
    expect(onDelete).toHaveBeenCalledWith('mem-1');
  });

  it('does not call onDelete when confirm returns false', () => {
    const onDelete = vi.fn();
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<MemoryItem memory={baseMemory} onDelete={onDelete} />);
    fireEvent.click(screen.getByTitle('删除记忆'));
    expect(onDelete).not.toHaveBeenCalled();
  });
});
