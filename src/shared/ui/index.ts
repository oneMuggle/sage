// 通用组件导出
export { Button } from './Button';

// U-Card: DESIGN.md §7 标准卡片容器 (bg-ui-card + border-ui-border + rounded-xl)
export { Card } from './Card';

export { Input } from './Input';

export { Modal } from './Modal';

export { LiveDot } from './LiveDot';
export type { LiveState } from './LiveDot';

export { AttnBadge, ATTN_BADGE_MAX_DISPLAY } from './AttnBadge';

// U-Brand: 共享品牌标识，favicon 之外所有 UI 位点都通过本组件复用
export { BrandLogo } from './BrandLogo';

// lazy 路由 chunk 加载期间的页面级骨架 fallback (Layout 内层 Suspense)
export { PageSkeleton } from './PageSkeleton/PageSkeleton';

// P1: 统一图片查看器（缩放/平移/ESC）— markdown 图片与工具产物媒体共用
export { Lightbox } from './Lightbox/Lightbox';

// P1: 统一 Tooltip（radix）— 替代原生 title
export { Tooltip } from './Tooltip/Tooltip';
