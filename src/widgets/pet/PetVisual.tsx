// src/widgets/pet/PetVisual.tsx
//
// 宠物渲染的唯一出口：descriptor + 当前状态 → DOM。动画全部由 pet.css 的
// CSS keyframes 驱动（Chromium 106 基线，无新依赖；对齐门禁见
// docs/plans/2026-09-18_desktop-pet-design.md §5）。内置包与 P2 导入包
// 都经过本组件渲染。

import type { CSSProperties } from 'react';

import { petAnimationClass, type PetPackDescriptor } from '../../features/pet/builtinPacks';
import type { PetState } from '../../features/pet/petStore';

export interface PetVisualProps {
  pack: PetPackDescriptor;
  state: PetState;
  /** 边长 px（默认 72；设置页预览用小号） */
  size?: number;
  className?: string;
}

export function PetVisual({ pack, state, size = 72, className }: PetVisualProps) {
  // --pet-size: pet.css 里状态道具（.pet-prop）字号按本体边长缩放
  const style = { width: size, height: size, '--pet-size': `${size}px` } as CSSProperties;
  return (
    <span
      data-testid="pet-visual"
      data-pet-id={pack.id}
      data-state={state}
      className={`pet-visual ${pack.bodyClass} ${petAnimationClass(pack, state)} ${className ?? ''}`}
      style={style}
      aria-hidden
    >
      <span className="pet-face">
        <i className="pet-eye" />
        <i className="pet-eye" />
      </span>
      <span className="pet-prop" />
    </span>
  );
}
