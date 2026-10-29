import type { ReactNode } from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';

import { markContextMenuOpen } from './contextMenuEvents';
import { ContextMenuItems } from './ContextMenuItems';
import { ContextMenuContent, ContextMenuRoot, ContextMenuTrigger } from './ContextMenuPrimitives';
import type { ContextMenuItemSpec } from './types';

export * from './ContextMenuPrimitives';
export type { ContextMenuItemSpec } from './types';

/**
 * 右键上下文菜单 —— 声明式包装（Radix ContextMenu）。
 *
 * 键盘（方向键 / Escape）、ARIA menu 语义、指针定位与视口翻转、
 * 子菜单与 checkbox 均来自 Radix；样式原子与 DropdownMenu 共用
 * （menuClasses.ts），保证左键下拉与右键菜单观感一致。
 *
 * @example
 * ```tsx
 * <ContextMenu items={() => [{ id: 'copy', label: '复制', onSelect: copy }]}>
 *   <SessionItem ... />
 * </ContextMenu>
 * ```
 *
 * 菜单项通过函数形式传入时会在**打开时**求值，因此可以直接读取
 * 当前组件状态（是否流式中、是否已置顶、是否有选区）。
 */

export interface ContextMenuProps {
  /** 菜单项；传函数时在打开时求值，可读取最新组件状态。 */
  items: ContextMenuItemSpec[] | (() => ContextMenuItemSpec[]);
  children: ReactNode;
  /**
   * false 时直接渲染 children、不挂右键监听（例如行内重命名输入框
   * 等可编辑态，应让 Electron 原生编辑菜单接管）。
   */
  enabled?: boolean;
  onOpenChange?: (open: boolean) => void;
}

export function ContextMenu({ items, children, enabled = true, onOpenChange }: ContextMenuProps) {
  if (!enabled) return <>{children}</>;
  return (
    <EnabledContextMenu items={items} onOpenChange={onOpenChange}>
      {children}
    </EnabledContextMenu>
  );
}

function EnabledContextMenu({ items, children, onOpenChange }: Omit<ContextMenuProps, 'enabled'>) {
  const [open, setOpen] = useState(false);
  const [snapshot, setSnapshot] = useState<ContextMenuItemSpec[]>([]);
  const openRef = useRef(false);

  // 组件在菜单打开期间被卸载（如虚拟列表回收、会话删除）时，
  // Radix 不再触发 onOpenChange(false) —— 手动归还全局打开计数。
  useEffect(
    () => () => {
      if (openRef.current) {
        openRef.current = false;
        markContextMenuOpen(false);
      }
    },
    [],
  );

  const handleOpenChange = useCallback(
    (next: boolean) => {
      if (next !== openRef.current) {
        openRef.current = next;
        markContextMenuOpen(next);
      }
      if (next) {
        setSnapshot(typeof items === 'function' ? items() : items);
      }
      setOpen(next);
      onOpenChange?.(next);
    },
    [items, onOpenChange],
  );

  return (
    <ContextMenuRoot open={open} onOpenChange={handleOpenChange}>
      <ContextMenuTrigger asChild onContextMenu={(e) => e.stopPropagation()}>
        {children}
      </ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuItems items={snapshot} />
      </ContextMenuContent>
    </ContextMenuRoot>
  );
}
