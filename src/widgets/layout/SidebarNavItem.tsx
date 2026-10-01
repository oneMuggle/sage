// src/widgets/layout/SidebarNavItem.tsx
// UX-IA R3 批次 0-4：侧栏导航项渲染去重。
//
// 此前 Sidebar.tsx 有三份同构的 nav 渲染拷贝（折叠 rail / 一级项 / 「更多」项），
// 外加页脚设置入口是第四份特例。差异只有「有无文字」「有无 Tooltip」「有无角标」，
// 却各自漂移：rail 有 Tooltip + aria、primary 有 AttnBadge、more 两样都没有。
// 这里把三种形态收敛到一个组件，行为取并集 —— 折叠态也带待处理角标
// （批次 0-5，修「折叠后提醒全部消失」）。
import { clsx } from 'clsx';
import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

import { Tooltip } from '../../shared/ui';

export interface SidebarNavItemData {
  path: string;
  label: string;
  icon: LucideIcon;
}

interface SidebarNavItemProps {
  item: SidebarNavItemData;
  /** 路由命中态（由调用方算好，rail 与 row 共享同一判定） */
  active: boolean;
  /**
   * rail = 56px 折叠态（纯图标 + Tooltip，角标改为右上角浮层）；
   * row  = 展开态（图标 + 文字 + 行尾角标）。
   */
  variant: 'rail' | 'row';
  /** 行尾角标 / 装饰。row 渲染在文字之后，rail 渲染为图标右上角浮层。 */
  trailing?: ReactNode;
  /** 无障碍标签覆盖（默认取 item.label） */
  ariaLabel?: string;
  /**
   * 锁定态（P1-7）：入口可见但不可直达。
   *
   * 未解锁时渲染成 <button> 而不是 <Link> —— 灰态链接点下去却进不去，
   * 比隐藏更糟，是另一种形式的欺骗。onRequestUnlock 负责弹用途说明与确认。
   */
  locked?: { hint: string; badge: string; onRequestUnlock: () => void };
}

const ACTIVE_CLASS = 'bg-primary/10 text-primary';
const INACTIVE_CLASS = 'text-text-secondary hover:bg-bg-hover';
/** 锁定态：明显弱于常规入口，但不隐藏 —— 「看不见」会被读成「不存在」 */
const LOCKED_CLASS = 'text-text-secondary/50 hover:bg-bg-hover';

export function SidebarNavItem({
  item,
  active,
  variant,
  trailing,
  ariaLabel,
  locked,
}: SidebarNavItemProps) {
  const Icon = item.icon;
  const label = ariaLabel ?? item.label;

  if (variant === 'rail') {
    // P1-7：锁定入口与常规入口同形同位，只是弱化 + 点击给说明。
    // Tooltip 直接带上用途，鼠标悬停即可判断要不要开，不必先点开被拦住。
    if (locked) {
      return (
        <Tooltip content={`${item.label} · ${locked.hint}`} side="right">
          <button
            type="button"
            onClick={locked.onRequestUnlock}
            aria-label={`${label}（${locked.badge}）`}
            data-testid={`sidebar-locked-${item.path.replace(/^\//, '')}`}
            data-locked="true"
            className={clsx(
              'relative flex items-center justify-center w-10 h-10 rounded-radius-sm transition-colors',
              LOCKED_CLASS,
            )}
          >
            <Icon className="w-5 h-5" />
            <span className="sr-only">{item.label}</span>
          </button>
        </Tooltip>
      );
    }

    return (
      <Tooltip content={item.label} side="right">
        <Link
          to={item.path}
          aria-label={label}
          className={clsx(
            'relative flex items-center justify-center w-10 h-10 rounded-radius-sm transition-colors',
            active ? ACTIVE_CLASS : INACTIVE_CLASS,
          )}
        >
          <Icon className="w-5 h-5" />
          {trailing && (
            // 折叠态没有文字，角标改为图标右上角浮层；-mr-1 让出右侧边距
            <span className="absolute top-0.5 right-0.5 -translate-y-1/2 translate-x-1/3">
              {trailing}
            </span>
          )}
          {/* sr-only 文本标签：rail 只有图标，但入口名仍需可被文本查询与朗读命中
              （aria-label 仍作为可访问名优先，两者在正常渲染下同为 item.label）。 */}
          <span className="sr-only">{item.label}</span>
        </Link>
      </Tooltip>
    );
  }

  return (
    <Link
      to={item.path}
      aria-label={label}
      className={clsx(
        'flex items-center gap-2.5 px-3 py-2 rounded-radius-sm transition-colors text-sm font-medium',
        active ? ACTIVE_CLASS : INACTIVE_CLASS,
      )}
    >
      <Icon className="w-4 h-4" />
      <span>{item.label}</span>
      {trailing}
    </Link>
  );
}
