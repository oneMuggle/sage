import { clsx } from 'clsx';

import { useI18n } from '../lib/i18n';

/**
 * BrandLogo — Sage 共享品牌标识组件。
 *
 * 单一来源：从 public/sage.svg 引用，所有"品牌识别位点"（favicon 之外的 UI）
 * 都通过本组件复用，避免散落的 inline SVG / 字母方块。
 *
 * 设计决策（2026-09）：
 * - 5 个 size: xs=16/ sm=24/ md=32/ lg=48/ xl=64。父组件控制 spacing（无内边距）。
 * - withWordmark 仅在 sm/md 启用有意义；其他 size 不推荐。
 * - data-testid 通过 props 透传，让 `welcome-avatar` 等历史 testid 复用。
 */
export type BrandLogoSize = 'xs' | 'sm' | 'md' | 'lg' | 'xl';

export interface BrandLogoProps {
  size?: BrandLogoSize;
  /** 仅 sm/md 推荐；显示 Sage wordmark（来自 i18n sidebar.brand） */
  withWordmark?: boolean;
  /** 自定义 alt 文本；默认使用 t('brand.alt') */
  alt?: string;
  className?: string;
  /** 测试 ID；让外部既有的 testid（如 welcome-avatar）能直接透传 */
  testId?: string;
}

const SIZE_CLASSES: Record<BrandLogoSize, string> = {
  xs: 'w-4 h-4',
  sm: 'w-6 h-6',
  md: 'w-8 h-8',
  lg: 'w-12 h-12',
  xl: 'w-16 h-16',
};

export function BrandLogo({
  size = 'md',
  withWordmark = false,
  alt,
  className,
  testId = 'brand-logo',
}: BrandLogoProps) {
  const { t } = useI18n();
  const resolvedAlt = alt ?? t('brand.alt');

  const img = (
    <img
      src="/sage.svg"
      alt={resolvedAlt}
      data-testid={testId}
      className={clsx(SIZE_CLASSES[size], className)}
      draggable={false}
    />
  );

  if (!withWordmark) {
    return img;
  }

  return (
    <span className="flex items-center gap-2">
      {img}
      <span className="font-semibold text-sm text-text">{t('sidebar.brand')}</span>
    </span>
  );
}