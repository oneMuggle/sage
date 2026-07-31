/**
 * A19 ToolChainWidget 测试
 * - chain 为 null / 无步骤时不渲染
 * - 有步骤时渲染标题、进度统计、进度条
 * - 每步显示工具名、状态、耗时
 * - error 步骤显示错误信息，done 步骤显示结果摘要
 * - formatStepDuration 毫秒/秒格式化
 */
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';

import type { ToolChainSnapshot } from '../../../shared/api';
import { formatStepDuration } from '../../../shared/lib/utils';
import { ToolChainWidget } from '../ToolChainWidget';

const makeChain = (overrides: Partial<ToolChainSnapshot> = {}): ToolChainSnapshot => ({
  chain_id: 'chain-abc123',
  description: 'Tool Execution',
  steps: [],
  current_step: 0,
  total_steps: 0,
  completed_steps: 0,
  progress: 0,
  ...overrides,
});

describe('ToolChainWidget', () => {
  it('renders nothing when chain is null', () => {
    const { container } = render(<ToolChainWidget chain={null} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders nothing when chain has no steps', () => {
    const { container } = render(<ToolChainWidget chain={makeChain()} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders header with progress stats', () => {
    const chain = makeChain({
      steps: [
        {
          step_id: 1,
          tool_name: 'calculator',
          args: { expression: '1+1' },
          status: 'done',
          result: '2',
          duration_ms: 250,
          error_message: '',
        },
        {
          step_id: 2,
          tool_name: 'bash',
          args: { command: 'ls' },
          status: 'running',
          result: '',
          duration_ms: 0,
          error_message: '',
        },
      ],
      current_step: 2,
      total_steps: 2,
      completed_steps: 1,
      progress: 0.5,
    });
    render(<ToolChainWidget chain={chain} />);

    expect(screen.getByText('工具链进度')).toBeInTheDocument();
    expect(screen.getByText('1/2 · 50%')).toBeInTheDocument();
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '50');
  });

  it('renders each step with tool name and duration', () => {
    const chain = makeChain({
      steps: [
        {
          step_id: 1,
          tool_name: 'calculator',
          args: { expression: '1+1' },
          status: 'done',
          result: '2',
          duration_ms: 1500,
          error_message: '',
        },
      ],
      total_steps: 1,
      completed_steps: 1,
      progress: 1,
    });
    render(<ToolChainWidget chain={chain} />);

    expect(screen.getByText('calculator')).toBeInTheDocument();
    expect(screen.getByText('1.5s')).toBeInTheDocument();
    expect(screen.getByTestId('tool-step-1')).toHaveAttribute('data-status', 'done');
  });

  it('shows args preview for steps with arguments', () => {
    const chain = makeChain({
      steps: [
        {
          step_id: 1,
          tool_name: 'bash',
          args: { command: 'git status' },
          status: 'running',
          result: '',
          duration_ms: 0,
          error_message: '',
        },
      ],
      current_step: 1,
      total_steps: 1,
    });
    render(<ToolChainWidget chain={chain} />);

    expect(screen.getByText('command=git status')).toBeInTheDocument();
    expect(screen.getByTestId('tool-step-1')).toHaveAttribute('data-status', 'running');
  });

  it('shows error message for failed steps', () => {
    const chain = makeChain({
      steps: [
        {
          step_id: 1,
          tool_name: 'bash',
          args: {},
          status: 'error',
          result: 'exit code 1',
          duration_ms: 80,
          error_message: 'command not found',
        },
      ],
      total_steps: 1,
      completed_steps: 1,
      progress: 1,
    });
    render(<ToolChainWidget chain={chain} />);

    expect(screen.getByText('command not found')).toBeInTheDocument();
    expect(screen.getByTestId('tool-step-1')).toHaveAttribute('data-status', 'error');
  });

  it('shows result summary for completed steps', () => {
    const chain = makeChain({
      steps: [
        {
          step_id: 1,
          tool_name: 'read_file',
          args: {},
          status: 'done',
          result: 'file contents here',
          duration_ms: 12,
          error_message: '',
        },
      ],
      total_steps: 1,
      completed_steps: 1,
      progress: 1,
    });
    render(<ToolChainWidget chain={chain} />);

    expect(screen.getByText('file contents here')).toBeInTheDocument();
  });

  it('renders placeholder duration for zero-ms steps', () => {
    const chain = makeChain({
      steps: [
        {
          step_id: 1,
          tool_name: 'bash',
          args: {},
          status: 'running',
          result: '',
          duration_ms: 0,
          error_message: '',
        },
      ],
      current_step: 1,
      total_steps: 1,
    });
    render(<ToolChainWidget chain={chain} />);

    expect(screen.getByText('—')).toBeInTheDocument();
  });
});

describe('formatStepDuration', () => {
  it('returns placeholder for non-positive values', () => {
    expect(formatStepDuration(0)).toBe('—');
    expect(formatStepDuration(-5)).toBe('—');
  });

  it('formats sub-second durations as milliseconds', () => {
    expect(formatStepDuration(80)).toBe('80ms');
    expect(formatStepDuration(999)).toBe('999ms');
  });

  it('formats multi-second durations with one decimal', () => {
    expect(formatStepDuration(1000)).toBe('1.0s');
    expect(formatStepDuration(1500)).toBe('1.5s');
    expect(formatStepDuration(61234)).toBe('61.2s');
  });
});
