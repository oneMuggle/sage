import { ChevronDown, ChevronRight, type LucideIcon } from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import { useCallback, useEffect, useState, type ReactNode } from 'react';

import { Tooltip } from '../../shared/ui';

const NAV_GROUP_STORAGE_PREFIX = 'sage:nav-group:';

function readCollapsed(groupKey: string, defaultValue: boolean): boolean {
  try {
    const raw = localStorage.getItem(`${NAV_GROUP_STORAGE_PREFIX}${groupKey}`);
    if (raw === null) return defaultValue;
    return raw === '1';
  } catch {
    return defaultValue;
  }
}

function writeCollapsed(groupKey: string, collapsed: boolean): void {
  try {
    localStorage.setItem(`${NAV_GROUP_STORAGE_PREFIX}${groupKey}`, collapsed ? '1' : '0');
  } catch {
    // localStorage unavailable
  }
}

interface NavGroupProps {
  groupKey: string;
  /** sr-only / tooltip label */
  label: string;
  /** 组代表图标（折叠态显示） */
  icon: LucideIcon;
  /** false = 始终展开，不渲染折叠控件 */
  collapsible: boolean;
  /** 默认折叠态（仅首次无 localStorage 值时生效） */
  defaultCollapsed?: boolean;
  children: ReactNode;
}

/**
 * Scheme 2 (P1): 侧栏 rail 导航分组。
 *
 * 56px rail 中的可折叠组：
 *   - `collapsible=false`（核心组）：始终展开，不渲染折叠按钮
 *   - `collapsible=true`（工具/高级组）：一个折叠按钮，展开态显示全部子项，
 *     折叠态仅显示组图标 + 右箭头指示器
 *
 * 折叠状态按 groupKey 持久化到 localStorage，跨页面刷新保留。
 */
export function NavGroup({
  groupKey,
  label,
  icon: GroupIcon,
  collapsible,
  defaultCollapsed = false,
  children,
}: NavGroupProps) {
  const [collapsed, setCollapsed] = useState(() =>
    collapsible ? readCollapsed(groupKey, defaultCollapsed) : false,
  );

  // Sync if collapsible prop changes (shouldn't in practice, but defensive)
  useEffect(() => {
    if (!collapsible && collapsed) setCollapsed(false);
  }, [collapsible, collapsed]);

  const handleToggle = useCallback(() => {
    if (!collapsible) return;
    setCollapsed((prev) => {
      const next = !prev;
      writeCollapsed(groupKey, next);
      return next;
    });
  }, [collapsible, groupKey]);

  const Chevron = collapsed ? ChevronRight : ChevronDown;

  return (
    <div data-testid={`sidebar-nav-group-${groupKey}`} className="w-full">
      {collapsible && (
        <Tooltip content={`${label}${collapsed ? '（已折叠）' : ''}`} side="right">
          <button
            type="button"
            onClick={handleToggle}
            aria-expanded={!collapsed}
            aria-label={`${label} ${collapsed ? '展开' : '折叠'}`}
            data-testid={`sidebar-nav-group-toggle-${groupKey}`}
            className="flex items-center justify-center w-10 h-6 mx-auto my-0.5 rounded-radius-sm text-text-secondary hover:bg-bg-hover hover:text-text-primary transition-colors"
          >
            <Chevron className="w-3 h-3" aria-hidden="true" />
            <span className="sr-only">
              {label} {collapsed ? '展开' : '折叠'}
            </span>
          </button>
        </Tooltip>
      )}
      <AnimatePresence initial={false}>
        {(!collapsible || !collapsed) && (
          <motion.div
            initial={collapsible ? { height: 0, opacity: 0 } : false}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15, ease: 'easeOut' }}
            className="overflow-hidden flex flex-col items-center gap-1"
          >
            {children}
          </motion.div>
        )}
      </AnimatePresence>
      {/* 折叠态：显示组图标作为占位 */}
      {collapsible && collapsed && (
        <div className="flex items-center justify-center w-10 h-10 mx-auto text-text-secondary/40">
          <GroupIcon className="w-4 h-4" aria-hidden="true" />
          <span className="sr-only">{label}（已折叠）</span>
        </div>
      )}
    </div>
  );
}
