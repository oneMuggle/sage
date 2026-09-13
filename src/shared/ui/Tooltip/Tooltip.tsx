// src/shared/ui/Tooltip/Tooltip.tsx
//
// P1 (UI 优化方案 2026-09-13): 统一 Tooltip 基建 —— 替代散落各处的原生
// title 属性（原生 title 有 ~1s 系统延迟、样式不可控、不触屏/键盘可达）。
// 基于 @radix-ui/react-tooltip（依赖已在，此前零使用）；每个实例自带
// Provider，消费方零接线成本。content 为空时透传 children 不包 DOM。

import * as RadixTooltip from '@radix-ui/react-tooltip';
import { type ReactNode } from 'react';

export interface TooltipProps {
  content: ReactNode;
  children: ReactNode;
  side?: 'top' | 'right' | 'bottom' | 'left';
  /** true 时等价于无 Tooltip（直接渲染 children） */
  disabled?: boolean;
}

export function Tooltip({ content, children, side = 'top', disabled }: TooltipProps) {
  if (disabled || content == null || content === '') {
    return <>{children}</>;
  }
  return (
    <RadixTooltip.Provider delayDuration={300} skipDelayDuration={100}>
      <RadixTooltip.Root>
        <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
        <RadixTooltip.Portal>
          <RadixTooltip.Content
            side={side}
            sideOffset={6}
            data-testid="tooltip-content"
            className="z-[80] rounded bg-ink text-bg px-2 py-1 text-xs shadow-md animate-fade-enter select-none max-w-64"
          >
            {content}
          </RadixTooltip.Content>
        </RadixTooltip.Portal>
      </RadixTooltip.Root>
    </RadixTooltip.Provider>
  );
}
