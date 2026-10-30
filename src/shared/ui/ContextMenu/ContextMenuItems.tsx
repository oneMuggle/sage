import {
  ContextMenuCheckboxItem,
  ContextMenuItem,
  ContextMenuLabel,
  ContextMenuSeparator,
  ContextMenuShortcut,
  ContextMenuSub,
  ContextMenuSubContent,
  ContextMenuSubTrigger,
} from './ContextMenuPrimitives';
import type { ContextMenuItemSpec } from './types';

function renderSpec(item: ContextMenuItemSpec) {
  if (item.hidden) return null;

  if (item.kind === 'separator') {
    return <ContextMenuSeparator key={item.id} />;
  }

  if (item.kind === 'label') {
    return <ContextMenuLabel key={item.id}>{item.label}</ContextMenuLabel>;
  }

  if (item.kind === 'checkbox') {
    return (
      <ContextMenuCheckboxItem
        key={item.id}
        checked={item.checked}
        disabled={item.disabled}
        onCheckedChange={item.onCheckedChange}
      >
        <span className="flex-1 truncate">{item.label}</span>
      </ContextMenuCheckboxItem>
    );
  }

  if (item.submenu && item.submenu.length > 0) {
    const Icon = item.icon;
    return (
      <ContextMenuSub key={item.id}>
        <ContextMenuSubTrigger disabled={item.disabled}>
          {Icon ? <Icon aria-hidden className="h-4 w-4 shrink-0 text-faint" /> : null}
          <span className="flex-1 truncate">{item.label}</span>
        </ContextMenuSubTrigger>
        <ContextMenuSubContent>
          <ContextMenuItems items={item.submenu} />
        </ContextMenuSubContent>
      </ContextMenuSub>
    );
  }

  const Icon = item.icon;
  return (
    <ContextMenuItem
      key={item.id}
      variant={item.destructive ? 'destructive' : 'default'}
      disabled={item.disabled}
      onSelect={() => {
        // handler 自行负责错误提示；此处兜底防止异步拒绝变成 unhandled rejection
        void Promise.resolve(item.onSelect()).catch(() => {});
      }}
    >
      {Icon ? <Icon aria-hidden className="h-4 w-4 shrink-0 text-faint" /> : null}
      <span className="flex-1 truncate">{item.label}</span>
      {item.shortcut ? <ContextMenuShortcut>{item.shortcut}</ContextMenuShortcut> : null}
    </ContextMenuItem>
  );
}

/** 将声明式 spec 渲染为 Radix 菜单树（含子菜单）。 */
export function ContextMenuItems({ items }: { items: readonly ContextMenuItemSpec[] }) {
  return <>{items.map((item) => renderSpec(item))}</>;
}
