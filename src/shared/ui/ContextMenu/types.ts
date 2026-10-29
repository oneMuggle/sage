import type { LucideIcon } from 'lucide-react';

/**
 * 声明式右键菜单描述。
 *
 * 菜单项在**打开时**求值（调用方以函数形式传入），因此可以直接读取
 * 组件当前状态（是否流式中、是否已置顶、是否有选区）决定文案与禁用态，
 * 而不需要把状态同步进菜单组件。
 */
export interface ContextMenuActionItem {
  kind?: 'item';
  id: string;
  label: string;
  icon?: LucideIcon;
  /** 仅显示真实绑定的快捷键提示；没有绑定就不要填。 */
  shortcut?: string;
  /** 危险操作（删除/回滚）以错误色渲染。 */
  destructive?: boolean;
  disabled?: boolean;
  hidden?: boolean;
  /** 子菜单项；存在时该项渲染为可展开子菜单。 */
  submenu?: ContextMenuItemSpec[];
  onSelect: () => void | Promise<void>;
}

export interface ContextMenuCheckboxItemSpec {
  kind: 'checkbox';
  id: string;
  label: string;
  checked: boolean;
  disabled?: boolean;
  hidden?: boolean;
  onCheckedChange: (next: boolean) => void;
}

export interface ContextMenuSeparatorSpec {
  kind: 'separator';
  id: string;
  hidden?: boolean;
}

export interface ContextMenuLabelSpec {
  kind: 'label';
  id: string;
  label: string;
  hidden?: boolean;
}

export type ContextMenuItemSpec =
  | ContextMenuActionItem
  | ContextMenuCheckboxItemSpec
  | ContextMenuSeparatorSpec
  | ContextMenuLabelSpec;

/** 过滤 hidden 项。 */
export function visibleMenuItems(items: readonly ContextMenuItemSpec[]): ContextMenuItemSpec[] {
  return items.filter((item) => !item.hidden);
}
