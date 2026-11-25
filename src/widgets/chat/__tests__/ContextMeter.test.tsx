// src/widgets/chat/__tests__/ContextMeter.test.tsx
// U17 上下文占用指示器测试；窗口映射走 modelWindows 真实表。
// 2026-11-25 (composer 状态条下沉): 组件改为受控展示（usage prop），
// 取数归 useSessionUsage hook —— 本测试不再 mock usageApi。
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';

import type { SessionUsage } from '../../../shared/api/usageApi';
import { ContextMeter } from '../ContextMeter';

function usageFixture(overrides: Partial<SessionUsage>): SessionUsage {
  return {
    session_id: 's1',
    requests: 1,
    prompt_tokens: 100_000,
    completion_tokens: 0,
    total_tokens: 100_000,
    estimated_cost_usd: 0,
    cached_tokens: 0,
    cache_read_tokens: 0,
    cache_creation_tokens: 0,
    cache_hit_rate: 0,
    last_model: 'claude-sonnet-4',
    last_prompt_tokens: 100_000,
    last_cached_tokens: 0,
    last_at_ms: 1,
    // Task 5 (2026-09-15): catalog-resolved window for claude-sonnet-4.
    // Backend resolves via model_catalog and stores in usage_events.last_effective_window
    // so ContextMeter mirrors the request's actual cap.
    effective_context_window: 200_000,
    last_context_breakdown: null,
    // 2026-10-28: 性能统计字段
    avg_latency_ms: null,
    p95_latency_ms: null,
    max_latency_ms: null,
    ...overrides,
  };
}

describe('ContextMeter', () => {
  it('usage 为 null 时不渲染', () => {
    const { container } = render(<ContextMeter usage={null} />);
    expect(container.querySelector('[data-testid="context-meter"]')).toBeNull();
  });

  it('无 last_prompt_tokens（尚无请求）时不渲染', () => {
    const { container } = render(
      <ContextMeter usage={usageFixture({ last_prompt_tokens: null, last_model: null })} />,
    );
    expect(container.querySelector('[data-testid="context-meter"]')).toBeNull();
  });

  it('按模型窗口映射显示百分比 (100k/200k = 50%)', () => {
    render(<ContextMeter usage={usageFixture({})} />);
    expect(screen.getByTestId('context-meter')).toBeInTheDocument();
    expect(screen.getByText('50%')).toBeInTheDocument();
  });

  it('≥90% 显示告警色文本', () => {
    render(<ContextMeter usage={usageFixture({ last_prompt_tokens: 190_000 })} />);
    expect(screen.getByText('95%').className).toContain('text-error');
  });

  it('tooltip 含 token 明细与缓存命中', () => {
    render(<ContextMeter usage={usageFixture({ last_cached_tokens: 40_000 })} />);
    const title = screen.getByTestId('context-meter').getAttribute('title') ?? '';
    expect(title).toContain('100.0k / 200.0k');
    expect(title).toContain('claude-sonnet-4');
    expect(title).toContain('40.0k');
  });

  it('点击展开分类明细弹层: 各类 token 数与占比 + 剩余空间', () => {
    render(
      <ContextMeter
        usage={usageFixture({
          last_context_breakdown: {
            categories: {
              tools: 20_000,
              system: 10_000,
              skills: 2_000,
              dynamic_context: 3_000,
              current_input: 5_000,
              history_tool: 30_000,
              history_assistant: 20_000,
              history_user: 10_000,
            },
            estimated_total: 98_000,
            prompt_tokens: 100_000,
            calibrated: true,
          },
        })}
      />,
    );
    fireEvent.click(screen.getByTestId('context-meter'));

    const popover = screen.getByTestId('context-meter-popover');
    expect(popover).toBeInTheDocument();
    // 30k/100k = 30% (占已用上下文比例)
    expect(popover.textContent).toContain('历史 · 工具结果');
    expect(popover.textContent).toContain('30.0k · 30%');
    expect(popover.textContent).toContain('工具定义');
    expect(popover.textContent).toContain('剩余空间');
    expect(screen.getByTestId('context-meter-stacked-bar')).toBeInTheDocument();
  });

  it('默认弹层向上展开并右缘对齐（composer 页脚场景）', () => {
    render(<ContextMeter usage={usageFixture({})} />);
    fireEvent.click(screen.getByTestId('context-meter'));
    const popover = screen.getByTestId('context-meter-popover');
    expect(popover.className).toContain('bottom-full');
    expect(popover.className).toContain('right-0');
  });

  it('placement=bottom / align=left 时切换弹层方向', () => {
    render(<ContextMeter usage={usageFixture({})} placement="bottom" align="left" />);
    fireEvent.click(screen.getByTestId('context-meter'));
    const popover = screen.getByTestId('context-meter-popover');
    expect(popover.className).toContain('top-full');
    expect(popover.className).toContain('left-0');
  });

  it('无明细快照时弹层显示回退提示', () => {
    render(<ContextMeter usage={usageFixture({})} />);
    fireEvent.click(screen.getByTestId('context-meter'));
    expect(screen.getByTestId('context-meter-popover').textContent).toContain('暂无分类明细');
  });
});
