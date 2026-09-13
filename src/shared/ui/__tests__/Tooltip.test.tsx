/**
 * P1 (UI 优化方案 2026-09-13): Tooltip 基建 — 渲染/空值透传行为。
 * 交互细节（延迟显隐）由 Radix 内部管理，不做交互断言。
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { Tooltip } from '../Tooltip/Tooltip';

describe('Tooltip', () => {
  it('渲染 children 并挂载触发器', () => {
    render(
      <Tooltip content="提示文案">
        <button type="button">按钮</button>
      </Tooltip>,
    );
    expect(screen.getByRole('button', { name: '按钮' })).toBeInTheDocument();
  });

  it('content 为空时透传 children 不包 wrapper', () => {
    render(
      <Tooltip content="">
        <button type="button">裸按钮</button>
      </Tooltip>,
    );
    expect(screen.getByRole('button', { name: '裸按钮' })).toBeInTheDocument();
    expect(screen.queryByTestId('tooltip-content')).not.toBeInTheDocument();
  });
});
