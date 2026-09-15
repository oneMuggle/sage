import { ChevronDown, ChevronRight, type LucideIcon } from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import type { ReactNode } from 'react';

import { useI18n } from '../../shared/lib/i18n';

interface SiderSectionProps {
  sectionKey: string;
  label: string;
  icon: LucideIcon;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  trailing?: ReactNode;
  render: () => ReactNode;
  /** 内容区最大高度，超出后滚动。用于限制长列表（如会话）占据空间 */
  maxHeight?: string;
}

export function SiderSection({
  sectionKey,
  label,
  icon: Icon,
  collapsed,
  onToggleCollapsed,
  trailing,
  render,
  maxHeight,
}: SiderSectionProps) {
  const { t } = useI18n();
  const Chevron = collapsed ? ChevronRight : ChevronDown;

  return (
    <section data-section-key={sectionKey} className="mt-1">
      <header className="flex items-center gap-1 px-3 py-1.5 group">
        <button
          type="button"
          onClick={onToggleCollapsed}
          aria-expanded={!collapsed}
          aria-label={collapsed ? t('sider.expand') : t('sider.collapse')}
          className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted hover:text-text"
        >
          <Chevron className="w-3 h-3" aria-hidden="true" />
          <Icon className="w-3.5 h-3.5" aria-hidden="true" />
          <span>{label}</span>
        </button>
        {trailing && <div className="ml-auto">{trailing}</div>}
      </header>
      {/* 2026-09-13 P0: 分区展开/收起高度动画 — 此前是条件渲染硬切。
          Chromium 106 (Electron 21) 不支持 grid-template-rows 0fr↔1fr 插值
          (107+ 才有)，用 motion 的 JS 测高实现 height:auto 动画；
          AnimatePresence initial={false} 保证首次挂载不播动画。 */}
      <AnimatePresence initial={false}>
        {!collapsed && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
            className="overflow-hidden"
          >
            <div
              className="px-1"
              style={maxHeight ? { maxHeight, overflowY: 'auto' } : undefined}
            >
              {render()}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}
