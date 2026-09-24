/**
 * TM2 (DSH 对标 R11): ContextPressureBadge 组件测试。
 *
 * 阈值语义：< 0.6 不渲染；0.6-0.8 琥珀；≥ 0.8 红。仅渲染当前会话的水位。
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { useStore } from '../../../shared/lib/store';
import { ContextPressureBadge } from '../ContextPressureBadge';

const SESSION = 'sess-1';

function setPressure(pressure: number, sessionId: string = SESSION) {
  useStore.setState({
    contextPressure: {
      session_id: sessionId,
      pressure,
      total_tokens: Math.round(pressure * 3000),
      budget_tokens: 3000,
    },
  });
}

describe('ContextPressureBadge', () => {
  it('pressure < 0.6 → 不渲染（默认安静）', () => {
    setPressure(0.4);
    render(<ContextPressureBadge sessionId={SESSION} />);
    expect(screen.queryByTestId('context-pressure-badge')).toBeNull();
  });

  it('0.6 ≤ pressure < 0.8 → 琥珀提示', () => {
    setPressure(0.65);
    render(<ContextPressureBadge sessionId={SESSION} />);
    const badge = screen.getByTestId('context-pressure-badge');
    expect(badge.textContent).toContain('65%');
    expect(badge.className).toContain('amber');
  });

  it('pressure ≥ 0.8 → 红色警示', () => {
    setPressure(0.9);
    render(<ContextPressureBadge sessionId={SESSION} />);
    const badge = screen.getByTestId('context-pressure-badge');
    expect(badge.textContent).toContain('90%');
    expect(badge.className).toContain('red');
  });

  it('其他会话的水位不渲染', () => {
    setPressure(0.9, 'sess-other');
    render(<ContextPressureBadge sessionId={SESSION} />);
    expect(screen.queryByTestId('context-pressure-badge')).toBeNull();
  });

  it('无水位数据 → 不渲染', () => {
    useStore.setState({ contextPressure: null });
    render(<ContextPressureBadge sessionId={SESSION} />);
    expect(screen.queryByTestId('context-pressure-badge')).toBeNull();
  });
});
