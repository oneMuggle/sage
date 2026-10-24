import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ModelPicker } from '../ModelPicker';

const mockModels = [
  { modelId: 'gpt-4', endpointName: 'OpenAI' },
  { modelId: 'claude-3-opus', endpointName: 'Anthropic' },
  { modelId: 'claude-3-sonnet', endpointName: 'Anthropic' },
];

describe('ModelPicker', () => {
  it('renders with default model label', () => {
    render(<ModelPicker value={null} onChange={vi.fn()} models={mockModels} globalModelId="gpt-4" />);
    expect(screen.getByText('跟随全局 (gpt-4)')).toBeInTheDocument();
  });

  it('renders with selected model', () => {
    render(<ModelPicker value="claude-3-opus" onChange={vi.fn()} models={mockModels} globalModelId="gpt-4" />);
    expect(screen.getByText('claude-3-opus · Anthropic')).toBeInTheDocument();
  });

  it('shows all available models in dropdown', () => {
    render(<ModelPicker value={null} onChange={vi.fn()} models={mockModels} globalModelId="gpt-4" />);
    fireEvent.click(screen.getByRole('combobox'));
    expect(screen.getByText('gpt-4 · OpenAI')).toBeInTheDocument();
    expect(screen.getByText('claude-3-opus · Anthropic')).toBeInTheDocument();
    expect(screen.getByText('claude-3-sonnet · Anthropic')).toBeInTheDocument();
  });

  it('calls onChange when selecting a model', () => {
    const onChange = vi.fn();
    render(<ModelPicker value={null} onChange={onChange} models={mockModels} globalModelId="gpt-4" />);
    fireEvent.click(screen.getByRole('combobox'));
    fireEvent.click(screen.getByText('claude-3-opus · Anthropic'));
    expect(onChange).toHaveBeenCalledWith('claude-3-opus');
  });

  it('shows "跟随全局" option', () => {
    const onChange = vi.fn();
    render(<ModelPicker value="claude-3-opus" onChange={onChange} models={mockModels} globalModelId="gpt-4" />);
    fireEvent.click(screen.getByRole('combobox'));
    expect(screen.getByText('跟随全局 (gpt-4)')).toBeInTheDocument();
  });

  it('shows empty state when no models available', () => {
    render(<ModelPicker value={null} onChange={vi.fn()} models={[]} globalModelId={null} />);
    fireEvent.click(screen.getByRole('combobox'));
    expect(screen.getByText('暂无可用模型')).toBeInTheDocument();
  });
});
