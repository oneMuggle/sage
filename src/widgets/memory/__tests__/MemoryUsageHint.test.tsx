import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { MEMORY_HINT_DISMISSED_KEY, MemoryUsageHint } from '../MemoryUsageHint';

describe('MemoryUsageHint (Task 4.1)', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('默认展开并展示四层记忆/页面操作/新能力三栏', () => {
    render(<MemoryUsageHint />);
    expect(screen.getByTestId('memory-usage-hint')).toBeInTheDocument();
    expect(screen.getByText('四层记忆')).toBeInTheDocument();
    expect(screen.getByText('页面操作')).toBeInTheDocument();
    expect(screen.getByText('新能力')).toBeInTheDocument();
    expect(screen.getByText('情景记忆')).toBeInTheDocument();
    expect(screen.getByText('批量清理')).toBeInTheDocument();
  });

  it('点击标题折叠内容，再次点击展开', () => {
    render(<MemoryUsageHint />);
    const toggle = screen.getByRole('button', { name: /如何使用记忆库/ });
    expect(toggle).toHaveAttribute('aria-expanded', 'true');

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('四层记忆')).not.toBeInTheDocument();

    fireEvent.click(toggle);
    expect(screen.getByText('四层记忆')).toBeInTheDocument();
  });

  it('关闭后写 localStorage 并隐藏', () => {
    render(<MemoryUsageHint />);
    fireEvent.click(screen.getByRole('button', { name: '关闭提示' }));
    expect(localStorage.getItem(MEMORY_HINT_DISMISSED_KEY)).toBe('1');
    expect(screen.queryByTestId('memory-usage-hint')).not.toBeInTheDocument();
  });

  it('已关闭状态直接不渲染', () => {
    localStorage.setItem(MEMORY_HINT_DISMISSED_KEY, '1');
    render(<MemoryUsageHint />);
    expect(screen.queryByTestId('memory-usage-hint')).not.toBeInTheDocument();
  });
});
