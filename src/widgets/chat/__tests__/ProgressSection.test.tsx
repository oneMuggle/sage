// src/widgets/chat/__tests__/ProgressSection.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';

import { ProgressSection } from '../progress/ProgressSection';

describe('ProgressSection', () => {
  it('shows iteration when > 0', () => {
    render(<ProgressSection iteration={3} streamingState="thinking" toolCalls={[]} isLoading />);
    expect(screen.getByText(/第 3 轮/)).toBeInTheDocument();
  });

  it('hides iteration when 0', () => {
    render(<ProgressSection iteration={0} streamingState={null} toolCalls={[]} isLoading={false} />);
    expect(screen.queryByText(/第 \d+ 轮/)).not.toBeInTheDocument();
  });

  it('shows thinking label while loading', () => {
    render(<ProgressSection iteration={0} streamingState="thinking" toolCalls={[]} isLoading />);
    expect(screen.getByText(/思考中/)).toBeInTheDocument();
  });

  it('shows idle state when not loading', () => {
    render(<ProgressSection iteration={0} streamingState={null} toolCalls={[]} isLoading={false} />);
    expect(screen.getByText(/等待输入/)).toBeInTheDocument();
  });

  it('renders tool call names', () => {
    const toolCalls = [
      { id: 'tc1', name: 'write_file', args: {} },
      { id: 'tc2', name: 'search', args: {} },
    ];
    render(<ProgressSection iteration={1} streamingState="tool_call" toolCalls={toolCalls} isLoading />);
    expect(screen.getByText('write_file')).toBeInTheDocument();
    expect(screen.getByText('search')).toBeInTheDocument();
  });
});
