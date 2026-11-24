// M6d: MiniChart 边界行为 —— 负值向下画、全零返回 null、非有限输入按 0。
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { hasChartPoints, MiniChart } from '../MiniChart';

describe('MiniChart (M6d boundaries)', () => {
  it('draws negative values below the zero baseline', () => {
    const { container } = render(
      <MiniChart categories={['A', 'B']} series={[{ name: '数量', values: [-2, 3] }]} />,
    );

    const rects = container.querySelectorAll('rect');
    expect(rects).toHaveLength(2);
    const [negative, positive] = Array.from(rects);
    // viewBox 高 40：零线 y=24；负值柱顶贴零线、向下延展，正值柱从顶向下。
    expect(Number(negative.getAttribute('y'))).toBeCloseTo(24);
    expect(Number(negative.getAttribute('height'))).toBeCloseTo(16);
    expect(Number(positive.getAttribute('y'))).toBeCloseTo(0);
    expect(Number(positive.getAttribute('height'))).toBeCloseTo(24);
    expect(negative.querySelector('title')?.textContent).toContain('-2');
    expect(positive.querySelector('title')?.textContent).toContain('3');
  });

  it('renders nothing when every point is zero', () => {
    const { container } = render(
      <MiniChart categories={['A', 'B']} series={[{ name: null, values: [0, 0] }]} />,
    );

    expect(container.querySelector('svg')).toBeNull();
  });

  it('treats non-finite values as zero instead of crashing', () => {
    const { container } = render(
      <MiniChart
        categories={['A', 'B', 'C']}
        series={[{ name: null, values: ['abc', Number.POSITIVE_INFINITY, 2] }]}
      />,
    );

    // 非有限值按 0 处理 → 不画柱；只有有限值 2 出柱。
    const rects = container.querySelectorAll('rect');
    expect(rects).toHaveLength(1);
    expect(rects[0].querySelector('title')?.textContent).toContain('2');
  });

  it('hasChartPoints is true only when some series has values', () => {
    expect(hasChartPoints([{ name: null, values: [1] }])).toBe(true);
    expect(hasChartPoints([{ name: null, values: [] }])).toBe(false);
    expect(hasChartPoints([])).toBe(false);
  });
});
