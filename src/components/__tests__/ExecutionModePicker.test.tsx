/**
 * ExecutionModePicker.test.tsx — 执行模式选择对话框测试（2026-10-28）。
 *
 * 覆盖：
 * - open=false → 不渲染
 * - open=true → 标题 + 两个模式按钮 + 取消按钮
 * - 点单 agent → onSelect('single') + onClose
 * - 点编排模式 → onSelect('multi') + onClose
 * - reasoning 非空 → 渲染分类依据区
 * - 点取消 → 仅 onClose，不 onSelect
 */

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ExecutionModePicker } from '../ExecutionModePicker';

afterEach(cleanup);

describe('ExecutionModePicker', () => {
  it('不渲染当 open=false', () => {
    const onSelect = vi.fn();
    const onClose = vi.fn();
    const { container } = render(
      <ExecutionModePicker open={false} onSelect={onSelect} onClose={onClose} />,
    );
    expect(container.innerHTML).toBe('');
    expect(onSelect).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('渲染标题 + 两个模式按钮 + 取消按钮当 open=true', () => {
    render(<ExecutionModePicker open={true} onSelect={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByText('选择执行模式')).toBeInTheDocument();
    expect(screen.getByText('单 agent（串行）')).toBeInTheDocument();
    expect(screen.getByText('编排模式（并行）')).toBeInTheDocument();
    expect(screen.getByText('取消（保留 plan 待审阅）')).toBeInTheDocument();
  });

  it('点单 agent 按钮 → onSelect("single") + onClose', () => {
    const onSelect = vi.fn();
    const onClose = vi.fn();
    render(<ExecutionModePicker open={true} onSelect={onSelect} onClose={onClose} />);
    fireEvent.click(screen.getByText('单 agent（串行）'));
    expect(onSelect).toHaveBeenCalledWith('single');
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('点编排模式按钮 → onSelect("multi") + onClose', () => {
    const onSelect = vi.fn();
    const onClose = vi.fn();
    render(<ExecutionModePicker open={true} onSelect={onSelect} onClose={onClose} />);
    fireEvent.click(screen.getByText('编排模式（并行）'));
    expect(onSelect).toHaveBeenCalledWith('multi');
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('reasoning 非空 → 渲染分类依据区', () => {
    render(
      <ExecutionModePicker
        open={true}
        onSelect={vi.fn()}
        onClose={vi.fn()}
        reasoning="步骤多，有并行可能"
      />,
    );
    expect(screen.getByText('分类依据：')).toBeInTheDocument();
    expect(screen.getByText('步骤多，有并行可能')).toBeInTheDocument();
  });

  it('reasoning 为空 → 不渲染分类依据区', () => {
    const { container } = render(
      <ExecutionModePicker open={true} onSelect={vi.fn()} onClose={vi.fn()} />,
    );
    expect(container.querySelector('.bg-bg-muted\\/40')).toBeNull();
  });

  it('点取消按钮 → 仅 onClose，不 onSelect', () => {
    const onSelect = vi.fn();
    const onClose = vi.fn();
    render(<ExecutionModePicker open={true} onSelect={onSelect} onClose={onClose} />);
    fireEvent.click(screen.getByText('取消（保留 plan 待审阅）'));
    expect(onSelect).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
