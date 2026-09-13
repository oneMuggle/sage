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
