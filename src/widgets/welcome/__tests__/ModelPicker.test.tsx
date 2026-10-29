import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { AUTO_MODEL_ID, ModelPicker } from '../ModelPicker';

const mockModels = [
  { modelId: 'gpt-4', endpointName: 'OpenAI' },
  { modelId: 'claude-3-opus', endpointName: 'Anthropic' },
  { modelId: 'claude-3-sonnet', endpointName: 'Anthropic' },
];

describe('ModelPicker', () => {
  it('renders with default model label', () => {
    render(
      <ModelPicker value={null} onChange={vi.fn()} models={mockModels} globalModelId="gpt-4" />,
    );
    expect(screen.getByText('跟随全局 (gpt-4)')).toBeInTheDocument();
  });

  it('renders with selected model', () => {
    render(
      <ModelPicker
        value="claude-3-opus"
        onChange={vi.fn()}
        models={mockModels}
        globalModelId="gpt-4"
      />,
    );
    expect(screen.getByText('claude-3-opus · Anthropic')).toBeInTheDocument();
  });

  it('shows all available models in dropdown', () => {
    render(
      <ModelPicker value={null} onChange={vi.fn()} models={mockModels} globalModelId="gpt-4" />,
    );
    fireEvent.click(screen.getByRole('combobox'));
    expect(screen.getByText('gpt-4 · OpenAI')).toBeInTheDocument();
    expect(screen.getByText('claude-3-opus · Anthropic')).toBeInTheDocument();
    expect(screen.getByText('claude-3-sonnet · Anthropic')).toBeInTheDocument();
  });

  it('calls onChange when selecting a model', () => {
    const onChange = vi.fn();
    render(
      <ModelPicker value={null} onChange={onChange} models={mockModels} globalModelId="gpt-4" />,
    );
    fireEvent.click(screen.getByRole('combobox'));
    fireEvent.click(screen.getByText('claude-3-opus · Anthropic'));
    expect(onChange).toHaveBeenCalledWith('claude-3-opus');
  });

  it('shows "跟随全局" option', () => {
    const onChange = vi.fn();
    render(
      <ModelPicker
        value="claude-3-opus"
        onChange={onChange}
        models={mockModels}
        globalModelId="gpt-4"
      />,
    );
    fireEvent.click(screen.getByRole('combobox'));
    expect(screen.getByText('跟随全局 (gpt-4)')).toBeInTheDocument();
  });

  it('shows empty state when no models available', () => {
    render(<ModelPicker value={null} onChange={vi.fn()} models={[]} globalModelId={null} />);
    fireEvent.click(screen.getByRole('combobox'));
    expect(screen.getByText('暂无可用模型')).toBeInTheDocument();
  });
});

describe('ModelPicker — auto routing and tier groups (Task 8)', () => {
  const groupedModels = [
    { modelId: 'power-model', endpointName: 'Ep', tier: 'powerful' },
    { modelId: 'fast-model', endpointName: 'Ep', tier: 'fast' },
    { modelId: 'unclassified-model', endpointName: 'Ep', tier: null },
    { modelId: 'balanced-model', endpointName: 'Ep', tier: 'balanced' },
  ];

  const groupLabels = (): (string | null)[] =>
    screen.getAllByText(/^(快速|均衡|强力|未分类)$/).map((element) => element.textContent);

  it('renders the auto routing option when autoAvailable is true and reports the sentinel', () => {
    const onChange = vi.fn();
    render(
      <ModelPicker
        value={null}
        onChange={onChange}
        models={mockModels}
        globalModelId="gpt-4"
        autoAvailable
      />,
    );
    fireEvent.click(screen.getByRole('combobox'));
    fireEvent.click(screen.getByText('自动路由（按任务选择模型）'));
    expect(onChange).toHaveBeenCalledWith(AUTO_MODEL_ID);
  });

  it('hides the auto routing option when autoAvailable is omitted', () => {
    render(
      <ModelPicker value={null} onChange={vi.fn()} models={mockModels} globalModelId="gpt-4" />,
    );
    fireEvent.click(screen.getByRole('combobox'));
    expect(screen.queryByText('自动路由（按任务选择模型）')).not.toBeInTheDocument();
  });

  it('shows the auto label in the trigger when value is the auto sentinel', () => {
    render(
      <ModelPicker
        value={AUTO_MODEL_ID}
        onChange={vi.fn()}
        models={mockModels}
        globalModelId="gpt-4"
        autoAvailable
      />,
    );
    expect(screen.getByText('自动路由（按任务选择模型）')).toBeInTheDocument();
  });

  it('groups models in fast, balanced, powerful, unclassified order', () => {
    render(
      <ModelPicker value={null} onChange={vi.fn()} models={groupedModels} globalModelId="gpt-4" />,
    );
    fireEvent.click(screen.getByRole('combobox'));
    expect(groupLabels()).toEqual(['快速', '均衡', '强力', '未分类']);
    expect(screen.getByText('fast-model · Ep')).toBeInTheDocument();
    expect(screen.getByText('balanced-model · Ep')).toBeInTheDocument();
    expect(screen.getByText('power-model · Ep')).toBeInTheDocument();
    expect(screen.getByText('unclassified-model · Ep')).toBeInTheDocument();
  });

  it('shows context window and price for grouped models', () => {
    render(
      <ModelPicker
        value={null}
        onChange={vi.fn()}
        models={[
          {
            modelId: 'cheap-model',
            endpointName: 'OpenAI',
            tier: 'fast',
            contextTokens: 128000,
            priceLabel: '0.15/0.60 USD/M',
          },
          { modelId: 'big-model', endpointName: 'OpenAI', tier: 'powerful' },
        ]}
        globalModelId="gpt-4"
      />,
    );
    fireEvent.click(screen.getByRole('combobox'));
    expect(screen.getByText('cheap-model · OpenAI · 128k · 0.15/0.60 USD/M')).toBeInTheDocument();
  });

  it('keeps the flat list when no model has tier data', () => {
    render(
      <ModelPicker value={null} onChange={vi.fn()} models={mockModels} globalModelId="gpt-4" />,
    );
    fireEvent.click(screen.getByRole('combobox'));
    expect(screen.queryByText('快速')).not.toBeInTheDocument();
    expect(screen.queryByText('均衡')).not.toBeInTheDocument();
    expect(screen.queryByText('强力')).not.toBeInTheDocument();
    expect(screen.queryByText('未分类')).not.toBeInTheDocument();
    expect(screen.getByText('gpt-4 · OpenAI')).toBeInTheDocument();
  });
});
