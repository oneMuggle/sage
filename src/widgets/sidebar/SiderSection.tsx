import { ChevronDown, ChevronRight, type LucideIcon } from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import { useState, type ReactNode } from 'react';

import { useI18n } from '../../shared/lib/i18n';

interface SiderSectionProps {
  sectionKey: string;
  label: string;
  icon: LucideIcon;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  trailing?: ReactNode;
  render: () => ReactNode;
  /**
   * 内容区最大高度，超出后内部滚动。用于限制长列表（如项目）占据空间。
   * 注意：必须与内层 `overflow-y-auto` 配对，只钳高度不滚动会把内容裁掉。
   */
  maxHeight?: string;
  /**
   * 填充父级剩余高度并在内部滚动（会话分区）。
   * fill 分区不播放展开/收起高度动画 —— flex 子项与 `height: auto` 动画冲突。
   */
  fill?: boolean;
}

export function formatSiderSectionAuditSnapshot(opts: {
  sectionKey?: string;
  label?: string;
  collapsed?: boolean;
  hasTrailing?: boolean;
  maxHeight?: string;
}): string {
  return `siderSection|key=${opts.sectionKey || 'none'}|label=${opts.label || 'none'}|collapsed=${opts.collapsed ? 1 : 0}|trailing=${opts.hasTrailing ? 1 : 0}|maxH=${opts.maxHeight || 'auto'}`;
}

export function formatSiderSectionAuditJson(opts: {
  sectionKey?: string;
  label?: string;
  collapsed?: boolean;
  hasTrailing?: boolean;
  maxHeight?: string;
}): string {
  return JSON.stringify({
    sectionKey: opts.sectionKey || 'none',
    label: opts.label || 'none',
    collapsed: Boolean(opts.collapsed),
    hasTrailing: Boolean(opts.hasTrailing),
    maxHeight: opts.maxHeight || 'auto',
  });
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
  fill = false,
}: SiderSectionProps) {
  const { t } = useI18n();
  const Chevron = collapsed ? ChevronRight : ChevronDown;
  const [copiedSnapshot, setCopiedSnapshot] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);
  /* v8 ignore start */
  const handleCopySnapshot = async () => {
    setCopiedSnapshot(true);
    try {
      await navigator.clipboard?.writeText(
        formatSiderSectionAuditSnapshot({
          sectionKey,
          label,
          collapsed,
          hasTrailing: Boolean(trailing),
          maxHeight,
        }),
      );
    } catch {
      // ignore
    }
  };
  const handleCopyJson = async () => {
    setCopiedJson(true);
    try {
      await navigator.clipboard?.writeText(
        formatSiderSectionAuditJson({
          sectionKey,
          label,
          collapsed,
          hasTrailing: Boolean(trailing),
          maxHeight,
        }),
      );
    } catch {
      // ignore
    }
  };
  /* v8 ignore stop */

  return (
    <section
      data-section-key={sectionKey}
      className={fill ? 'mt-1 flex-1 min-h-0 flex flex-col' : 'mt-1'}
    >
      <header className="flex items-center gap-1 px-3 py-1.5 group flex-shrink-0">
        <button
          type="button"
          onClick={onToggleCollapsed}
          aria-expanded={!collapsed}
          aria-label={collapsed ? t('sider.expand') : t('sider.collapse')}
          className="inline-flex items-center gap-1.5 text-ui-2xs font-semibold uppercase tracking-wide text-muted hover:text-text"
        >
          <Chevron className="w-3 h-3" aria-hidden="true" />
          <Icon className="w-3.5 h-3.5" aria-hidden="true" />
          <span>{label}</span>
        </button>
        {trailing && <div className="ml-auto">{trailing}</div>}
        <span data-testid="sider-section-copy-snapshot" onClick={() => void handleCopySnapshot()}>
          {copiedSnapshot ? '已复制快照' : ''}
        </span>
        <span data-testid="sider-section-copy-json" onClick={() => void handleCopyJson()}>
          {copiedJson ? '已复制JSON' : ''}
        </span>
      </header>
      {fill ? (
        !collapsed && <div className="px-1 flex-1 min-h-0 min-w-0 flex flex-col">{render()}</div>
      ) : (
        <AnimatePresence initial={false}>
          {!collapsed && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.18, ease: 'easeOut' }}
              className="overflow-hidden"
            >
              {/* 高度上限必须与内层滚动配对：UX-IA R3 曾只保留 maxHeight 而移除
                  overflow-y-auto，导致超出上限的列表被 overflow-hidden 直接裁掉。 */}
              <div
                className={maxHeight ? 'px-1 overflow-y-auto' : 'px-1'}
                style={maxHeight ? { maxHeight } : undefined}
              >
                {render()}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      )}
    </section>
  );
}
