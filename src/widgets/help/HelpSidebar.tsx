import { useState } from 'react';

export interface HelpItem {
  id: string;
  title: string;
  type: 'builtin' | 'user-manual';
  children?: HelpItem[];
  filename?: string;
}

interface HelpSidebarProps {
  items: HelpItem[];
  activeItem: string;
  onItemClick: (id: string) => void;
}

export function HelpSidebar({ items, activeItem, onItemClick }: HelpSidebarProps) {
  return (
    <nav
      className="w-60 border-r border-border overflow-y-auto bg-surface flex-shrink-0"
      aria-label="帮助目录"
    >
      <div className="p-4">
        <h2 className="text-sm font-semibold text-text-secondary mb-3 flex items-center gap-2">
          <span>📚</span>
          <span>目录</span>
        </h2>
        <ul className="space-y-1">
          {items.map((item) => (
            <SidebarItem
              key={item.id}
              item={item}
              activeItem={activeItem}
              onItemClick={onItemClick}
              depth={0}
            />
          ))}
        </ul>
      </div>
    </nav>
  );
}

interface SidebarItemProps {
  item: HelpItem;
  activeItem: string;
  onItemClick: (id: string) => void;
  depth: number;
}

function SidebarItem({ item, activeItem, onItemClick, depth }: SidebarItemProps) {
  const [isExpanded, setIsExpanded] = useState(true);
  const isActive = activeItem === item.id;
  const hasChildren = item.children && item.children.length > 0;
  const isSeparator = item.id === 'user-manual-separator';

  if (isSeparator) {
    return (
      <li className="pt-4 pb-2">
        <div className="border-t border-border" />
        <h3 className="text-xs font-semibold text-text-secondary mt-2">{item.title}</h3>
      </li>
    );
  }

  return (
    <li>
      <button
        onClick={() => {
          if (hasChildren) {
            setIsExpanded(!isExpanded);
          } else {
            onItemClick(item.id);
          }
        }}
        className={`w-full flex items-center gap-2 px-3 py-2 text-left rounded-radius-sm transition-colors ${
          isActive
            ? 'bg-primary/10 text-primary'
            : 'text-text-secondary hover:text-text hover:bg-bg-hover'
        }`}
        style={{ paddingLeft: `${depth * 12 + 12}px` }}
      >
        {hasChildren && (
          <span className="text-xs text-text-secondary flex-shrink-0">
            {isExpanded ? '▼' : '▶'}
          </span>
        )}
        <span className="text-sm flex-1">{item.title}</span>
        {item.type === 'user-manual' && (
          <span className="text-xs text-text-secondary" title="外部文档">
            📖
          </span>
        )}
      </button>
      {hasChildren && isExpanded && (
        <ul className="space-y-1 mt-1">
          {item.children!.map((child) => (
            <SidebarItem
              key={child.id}
              item={child}
              activeItem={activeItem}
              onItemClick={onItemClick}
              depth={depth + 1}
            />
          ))}
        </ul>
      )}
    </li>
  );
}
