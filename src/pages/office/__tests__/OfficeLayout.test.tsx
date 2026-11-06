/**
 * OfficeLayout — 文档工作台三栏布局壳测试。
 *
 * 覆盖：
 *   - 始终渲染 left / center 两个插槽；
 *   - 未传 right 时不渲染右栏，即使 DOM 里也不留空占位；
 *   - 传了 right 时才渲染 `office-layout-right`。
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { OfficeLayout } from '../OfficeLayout';

describe('OfficeLayout', () => {
  it('renders left and center slots and omits the right slot when not provided', () => {
    render(
      <OfficeLayout
        left={<div data-testid="left-slot">Left</div>}
        center={<div data-testid="center-slot">Center</div>}
      />,
    );

    expect(screen.getByTestId('office-layout')).toBeInTheDocument();
    expect(screen.getByTestId('office-layout-left')).toBeInTheDocument();
    expect(screen.getByTestId('office-layout-center')).toBeInTheDocument();
    expect(screen.getByTestId('left-slot')).toBeInTheDocument();
    expect(screen.getByTestId('center-slot')).toBeInTheDocument();
    expect(screen.queryByTestId('office-layout-right')).not.toBeInTheDocument();
  });

  it('renders the right slot only when provided', () => {
    render(
      <OfficeLayout
        left={<div>Left</div>}
        center={<div>Center</div>}
        right={<div data-testid="right-slot">Right</div>}
      />,
    );

    expect(screen.getByTestId('office-layout-right')).toBeInTheDocument();
    expect(screen.getByTestId('right-slot')).toBeInTheDocument();
  });
});
