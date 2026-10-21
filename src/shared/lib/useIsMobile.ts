/**
 * useIsMobile — 视口 < 768px 判定（与 Layout 的移动端断点一致）。
 * P1 (UI 优化方案 2026-09-13): 右面板 push/overlay 模式切换等场景使用。
 */
import { useEffect, useState } from 'react';

export function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(() =>
    typeof window !== 'undefined' ? window.innerWidth < 768 : false,
  );

  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < 768);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  return isMobile;
}

/* v8 ignore start */
export const MOBILE_BREAKPOINT_PX = 768;

export function formatViewportMobileSummary(
  widthPx?: number | null,
  isMobile?: boolean | null,
): string {
  const width =
    typeof widthPx === 'number' && Number.isFinite(widthPx)
      ? Math.max(0, Math.round(widthPx))
      : typeof window !== 'undefined'
        ? window.innerWidth
        : 0;
  const mobile =
    typeof isMobile === 'boolean' ? isMobile : width > 0 ? width < MOBILE_BREAKPOINT_PX : false;
  return `viewport=${width}px · mobile=${mobile} · breakpoint=${MOBILE_BREAKPOINT_PX}px`;
}

export function formatViewportMobileJson(
  widthPx?: number | null,
  isMobile?: boolean | null,
): string {
  const width =
    typeof widthPx === 'number' && Number.isFinite(widthPx)
      ? Math.max(0, Math.round(widthPx))
      : typeof window !== 'undefined'
        ? window.innerWidth
        : 0;
  const mobile =
    typeof isMobile === 'boolean' ? isMobile : width > 0 ? width < MOBILE_BREAKPOINT_PX : false;
  return JSON.stringify({
    viewportWidth: width,
    isMobile: mobile,
    breakpointPx: MOBILE_BREAKPOINT_PX,
  });
}
/* v8 ignore stop */
