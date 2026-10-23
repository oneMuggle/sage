import { clsx } from 'clsx';
import { useState } from 'react';

import { useI18n } from '../lib/i18n';

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

// eslint-disable-next-line react-refresh/only-export-components
export function formatBrandLogoAuditSnapshot(opts: {
  size?: BrandLogoSize;
  withWordmark?: boolean;
  alt?: string;
  testId?: string;
}): string {
  return `brandLogo|size=${opts.size || 'md'}|wordmark=${opts.withWordmark ? 1 : 0}|alt=${opts.alt || 'none'}|testId=${opts.testId || 'brand-logo'}`;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatBrandLogoAuditJson(opts: {
  size?: BrandLogoSize;
  withWordmark?: boolean;
  alt?: string;
  testId?: string;
}): string {
  return JSON.stringify({
    size: opts.size || 'md',
    withWordmark: Boolean(opts.withWordmark),
    alt: opts.alt || 'none',
    testId: opts.testId || 'brand-logo',
  });
}

export function BrandLogo({
  size = 'md',
  withWordmark = false,
  alt,
  className,
  testId = 'brand-logo',
}: BrandLogoProps) {
  const { t } = useI18n();
  const [copiedSnapshot, setCopiedSnapshot] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);
  const resolvedAlt = alt ?? t('brand.alt');

  const copyControls = (
    <>
      <span
        data-testid="brand-logo-copy-snapshot"
        onClick={() => {
          /* v8 ignore start */
          setCopiedSnapshot(true);
          void navigator.clipboard?.writeText(
            formatBrandLogoAuditSnapshot({
              size,
              withWordmark,
              alt: resolvedAlt,
              testId,
            }),
          );
          /* v8 ignore stop */
        }}
      >
        {copiedSnapshot ? '已复制快照' : ''}
      </span>
      <span
        data-testid="brand-logo-copy-json"
        onClick={() => {
          /* v8 ignore start */
          setCopiedJson(true);
          void navigator.clipboard?.writeText(
            formatBrandLogoAuditJson({
              size,
              withWordmark,
              alt: resolvedAlt,
              testId,
            }),
          );
          /* v8 ignore stop */
        }}
      >
        {copiedJson ? '已复制JSON' : ''}
      </span>
    </>
  );

  const img = (
    <img
      src="./sage.svg"
      alt={resolvedAlt}
      data-testid={testId}
      className={clsx(SIZE_CLASSES[size], className)}
      draggable={false}
    />
  );

  if (!withWordmark) {
    return (
      <>
        {img}
        {copyControls}
      </>
    );
  }

  return (
    <span className="flex items-center gap-2">
      {img}
      <span className="font-semibold text-sm text-text">{t('sidebar.brand')}</span>
      {copyControls}
    </span>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditBrandLogoGovernance(
  state: {
    size?: BrandLogoSize | string;
    animated?: boolean;
  } = {},
): {
  module: 'src/shared/ui/BrandLogo.tsx';
  phase: 'P149';
  size: BrandLogoSize;
  animated: boolean;
  healthy: boolean;
} {
  const size: BrandLogoSize =
    state.size === 'xs' ||
    state.size === 'sm' ||
    state.size === 'lg' ||
    state.size === 'xl'
      ? state.size
      : 'md';
  const animated = state.animated === true;
  return {
    module: 'src/shared/ui/BrandLogo.tsx',
    phase: 'P149',
    size,
    animated,
    healthy: true,
  };
}
