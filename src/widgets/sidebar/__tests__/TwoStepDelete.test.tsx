/**
 * TwoStepDelete 测试 — U12: 两步式删除确认（无 modal）
 *
 * 覆盖：第一次点击仅 armed / 第二次点击确认删除 / 超时自动解除 /
 *       Esc 提前解除 / disabled / 阻止事件冒泡 / 自定义 props
 */
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { TwoStepDelete } from '../TwoStepDelete';

describe('TwoStepDelete', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('第一次点击不删除，进入 armed 状态', () => {
    const onConfirm = vi.fn();
    render(<TwoStepDelete onConfirm={onConfirm} />);

    fireEvent.click(screen.getByRole('button', { name: '删除' }));

    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByRole('button')).toHaveAttribute('data-state', 'armed');
    expect(screen.getByText('确认删除?')).toBeInTheDocument();
  });

  it('第二次点击触发 onConfirm 一次并回到 idle', () => {
    const onConfirm = vi.fn();
    render(<TwoStepDelete onConfirm={onConfirm} />);

    fireEvent.click(screen.getByRole('button', { name: '删除' }));
    fireEvent.click(screen.getByRole('button', { name: '确认删除?' }));

    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button')).toHaveAttribute('data-state', 'idle');
  });

  it('超时自动 disarm；之后点击需重新 armed 才删除', () => {
    const onConfirm = vi.fn();
    render(<TwoStepDelete onConfirm={onConfirm} disarmTimeoutMs={3000} />);

    fireEvent.click(screen.getByRole('button', { name: '删除' }));
    act(() => {
      vi.advanceTimersByTime(3000);
    });

    expect(screen.getByRole('button')).toHaveAttribute('data-state', 'idle');

    // 超时后的下一次点击是重新 armed，而不是直接删除
    fireEvent.click(screen.getByRole('button', { name: '删除' }));
    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByRole('button')).toHaveAttribute('data-state', 'armed');
  });

  it('Esc 提前解除 armed 状态', () => {
    const onConfirm = vi.fn();
    render(<TwoStepDelete onConfirm={onConfirm} />);

    fireEvent.click(screen.getByRole('button', { name: '删除' }));
    fireEvent.keyDown(screen.getByRole('button', { name: '确认删除?' }), { key: 'Escape' });

    expect(screen.getByRole('button')).toHaveAttribute('data-state', 'idle');

    // 解除后再点击仍是 armed，不会删除
    fireEvent.click(screen.getByRole('button', { name: '删除' }));
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('disabled 时不 arm 也不删除', () => {
    const onConfirm = vi.fn();
    render(<TwoStepDelete onConfirm={onConfirm} disabled />);

    fireEvent.click(screen.getByRole('button'));

    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByRole('button')).toHaveAttribute('data-state', 'idle');
  });

  it('阻止事件冒泡，不触发外层行点击', () => {
    const onRowClick = vi.fn();
    render(
      <div onClick={onRowClick}>
        <TwoStepDelete onConfirm={() => undefined} />
      </div>,
    );

    fireEvent.click(screen.getByRole('button'));

    expect(onRowClick).not.toHaveBeenCalled();
  });

  it('支持自定义 label / armedLabel / icon / data-testid', () => {
    render(
      <TwoStepDelete
        onConfirm={() => undefined}
        label="删除记忆"
        armedLabel="确定?"
        data-testid="mem-del"
        icon={<span>×</span>}
      />,
    );

    const button = screen.getByTestId('mem-del');
    expect(button).toHaveAttribute('aria-label', '删除记忆');

    fireEvent.click(button);

    expect(button).toHaveAttribute('aria-label', '确定?');
    expect(screen.getByText('确定?')).toBeInTheDocument();
  });
});
