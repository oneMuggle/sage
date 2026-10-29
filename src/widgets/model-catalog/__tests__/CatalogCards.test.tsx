/**
 * CatalogCards 行为测试 (Task 10, 2026-10-28)
 *
 * 校验与 CatalogTable 共用的卡片契约:
 * - 加载态 / 空态文案 (与表格一致)
 * - 标题 / tier / 能力 / 上下文 / 价格渲染
 * - 点击与 Enter/Space 触发选中, 选中态 aria-selected
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { CandidateModel } from '../../../entities/model-catalog/types';
import { CatalogCards } from '../CatalogCards';
import { catalogItemKey } from '../CatalogTable';

const item: CandidateModel = {
  model_key: { provider: 'openrouter', model_id: 'anthropic/claude-3.5-sonnet' },
  tier: 'powerful',
  native: 200000,
  price: { input_per_million: '3.0', output_per_million: '15.0', currency: 'USD' },
  capabilities: { vision: true, tool_use: true, json: false, reasoning: true },
  source: 'openrouter',
  pricing_scope: 'base',
};

describe('CatalogCards', () => {
  it('loading 时渲染加载态文案', () => {
    render(<CatalogCards items={[item]} selectedKey={null} onSelect={vi.fn()} loading />);

    expect(screen.getByTestId('catalog-cards-loading')).toHaveTextContent('加载中');
    expect(screen.queryByTestId('catalog-cards')).not.toBeInTheDocument();
  });

  it('空列表显示与表格一致的空态文案', () => {
    render(<CatalogCards items={[]} selectedKey={null} onSelect={vi.fn()} />);

    expect(screen.getByTestId('catalog-cards-empty')).toHaveTextContent(
      '暂无模型, 请尝试同步 OpenRouter 或导入快照',
    );
  });

  it('渲染标题 / tier / 能力 / 上下文 / 价格 / 来源', () => {
    render(<CatalogCards items={[item]} selectedKey={null} onSelect={vi.fn()} />);

    expect(screen.getByText('openrouter/anthropic/claude-3.5-sonnet')).toBeInTheDocument();
    expect(screen.getByTestId('catalog-card-tier')).toHaveTextContent('强力');
    expect(screen.getByText('视觉')).toBeInTheDocument();
    expect(screen.getByText('工具')).toBeInTheDocument();
    expect(screen.getByText('推理')).toBeInTheDocument();
    // 值为 false 的能力不展示
    expect(screen.queryByText('JSON')).not.toBeInTheDocument();
    expect(screen.getByText(/200,000 tokens/)).toBeInTheDocument();
    expect(screen.getByText('入 $3.0 / 出 $15.0')).toBeInTheDocument();
    expect(screen.getByText('openrouter · base')).toBeInTheDocument();
  });

  it('tier / 能力 / 上下文 / 价格缺失时显示未知', () => {
    const unclassified: CandidateModel = {
      ...item,
      tier: null,
      native: null,
      capabilities: null,
      price: { input_per_million: null, output_per_million: null, currency: 'USD' },
    };
    render(<CatalogCards items={[unclassified]} selectedKey={null} onSelect={vi.fn()} />);

    expect(screen.getByTestId('catalog-card-tier')).toHaveTextContent('未知');
    expect(screen.getByText('能力未知')).toBeInTheDocument();
    expect(screen.getAllByText('未知')).toHaveLength(2);
    expect(screen.getByText('入 未知 / 出 未知')).toBeInTheDocument();
  });

  it('未收录的能力名原样展示', () => {
    const custom: CandidateModel = { ...item, capabilities: { audio: true, vision: false } };
    render(<CatalogCards items={[custom]} selectedKey={null} onSelect={vi.fn()} />);

    expect(screen.getByTestId('catalog-card-capability-audio')).toHaveTextContent('audio');
    expect(screen.queryByTestId('catalog-card-capability-vision')).not.toBeInTheDocument();
  });

  it('点击卡片触发 onSelect', () => {
    const onSelect = vi.fn();
    render(<CatalogCards items={[item]} selectedKey={null} onSelect={onSelect} />);

    fireEvent.click(screen.getByTestId(`catalog-card-${catalogItemKey(item)}`));

    expect(onSelect).toHaveBeenCalledWith(item);
  });

  it('Enter / Space 触发 onSelect', () => {
    const onSelect = vi.fn();
    render(<CatalogCards items={[item]} selectedKey={null} onSelect={onSelect} />);
    const card = screen.getByTestId(`catalog-card-${catalogItemKey(item)}`);

    fireEvent.keyDown(card, { key: 'Enter' });
    fireEvent.keyDown(card, { key: ' ' });

    expect(onSelect).toHaveBeenCalledTimes(2);
  });

  it('选中卡片设置 aria-selected', () => {
    render(<CatalogCards items={[item]} selectedKey={catalogItemKey(item)} onSelect={vi.fn()} />);

    const card = screen.getByTestId(`catalog-card-${catalogItemKey(item)}`);
    expect(card).toHaveAttribute('aria-selected', 'true');
  });
});
