/**
 * 菜单样式原子 —— DropdownMenu 与 ContextMenu 共用，避免两套菜单样式漂移。
 *
 * 语义色阶（ink / faint / line）与既有 DropdownMenu 一致；
 * 修改此处会同时影响左键下拉与右键菜单。
 */

export const MENU_CONTENT_CLASS =
  'z-50 min-w-[10rem] max-w-[22rem] overflow-hidden rounded-lg border border-line bg-bg p-1 shadow-lg animate-fade-enter';

export const MENU_ITEM_BASE_CLASS =
  'relative flex cursor-default select-none items-center gap-2 rounded-md px-2 py-1.5 text-sm outline-none transition-colors data-[disabled]:pointer-events-none data-[disabled]:opacity-50';

export const MENU_ITEM_CLASS = `${MENU_ITEM_BASE_CLASS} text-ink data-[highlighted]:bg-bg-hover`;

export const MENU_ITEM_DESTRUCTIVE_CLASS = `${MENU_ITEM_BASE_CLASS} text-error data-[highlighted]:bg-error/10`;

export const MENU_CHECK_ITEM_CLASS =
  'relative flex cursor-default select-none items-center rounded-md py-1.5 pl-8 pr-2 text-sm text-ink outline-none transition-colors data-[highlighted]:bg-bg-hover data-[disabled]:pointer-events-none data-[disabled]:opacity-50';

export const MENU_LABEL_CLASS = 'px-2 py-1.5 text-xs font-medium text-faint';

export const MENU_SEPARATOR_CLASS = '-mx-1 my-1 h-px bg-line';

export const MENU_SHORTCUT_CLASS = 'ml-auto text-xs tracking-widest text-faint';

export const MENU_SUB_TRIGGER_CLASS =
  'flex cursor-default select-none items-center gap-2 rounded-md px-2 py-1.5 text-sm text-ink outline-none transition-colors data-[highlighted]:bg-bg-hover data-[state=open]:bg-bg-hover data-[disabled]:pointer-events-none data-[disabled]:opacity-50';
